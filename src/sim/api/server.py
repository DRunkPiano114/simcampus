"""FastAPI server for God Mode, Role Play chat, and share-card rendering."""

import asyncio
import json
from urllib.parse import quote

from litellm.exceptions import ContextWindowExceededError  # pyright: ignore[reportPrivateImportUsage]
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from ..agent.storage import WorldStorage
from ..cards import aggregations as card_agg
from ..cards import cache as card_cache
from ..cards import captions as card_captions
from ..cards import agent_card, daily_card, scene_card
from ..llm.client import streaming_text_call, structured_call
from ..llm.prompts import render
from .context import build_context_at_timepoint
from .models import AgentReaction, AgentReactionLLM, ChatRequest, RolePlayRequest

_TOKEN_LIMIT_MSG = "对话太长了，请关闭后重新开始对话"

app = FastAPI(title="SimCampus API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared world storage instance (loaded once)
_world: WorldStorage | None = None


def _get_world() -> WorldStorage:
    global _world
    if _world is None:
        _world = WorldStorage()
        _world.load_all_agents()
    return _world


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/agents")
async def list_agents():
    world = _get_world()
    agents = {}
    for aid, storage in world.agents.items():
        profile = storage.load_profile()
        agents[aid] = {"name": profile.name, "role": profile.role.value}
    return {"agents": agents}


@app.post("/api/god-mode/chat")
async def god_mode_chat(req: ChatRequest):
    world = _get_world()
    ctx = build_context_at_timepoint(req.agent_id, req.day, req.time_period, world)

    system_prompt = render("god_mode.j2", **ctx)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in req.history:
        role = "user" if msg.role == "user" else "assistant"
        messages.append({"role": role, "content": msg.content})
    messages.append({"role": "user", "content": req.message})

    async def event_generator():
        try:
            async for token in streaming_text_call(messages):
                yield {"data": json.dumps({"token": token}, ensure_ascii=False)}
        except ContextWindowExceededError:
            yield {"data": json.dumps({"error": _TOKEN_LIMIT_MSG}, ensure_ascii=False)}
        except Exception as e:
            yield {"data": json.dumps({"error": str(e)}, ensure_ascii=False)}
        yield {"data": json.dumps({"done": True})}

    return EventSourceResponse(event_generator())


@app.post("/api/role-play/chat")
async def role_play_chat(req: RolePlayRequest):
    world = _get_world()

    # Validate up-front so a bad id surfaces as 404 instead of a stream-time 500
    # (and never reaches get_agent's strict KeyError path).
    for aid in (req.user_agent_id, *req.target_agent_ids):
        if aid not in world.agents:
            raise HTTPException(status_code=404, detail=f"unknown agent: {aid}")

    # Build context for user's character (to know their name)
    user_storage = world.get_agent(req.user_agent_id)
    user_profile = user_storage.load_profile()
    user_name = user_profile.name

    # Build context for each target agent
    target_contexts = {}
    for aid in req.target_agent_ids:
        target_contexts[aid] = build_context_at_timepoint(aid, req.day, req.time_period, world)

    async def event_generator():
        # Signal thinking state
        yield {"data": json.dumps({
            "thinking": True,
            "agent_ids": req.target_agent_ids,
        }, ensure_ascii=False)}

        # Build conversation history for templates
        conv_history = [
            {"agent_name": msg.agent_name or msg.role, "content": msg.content}
            for msg in req.history
        ]

        # Build user message (variable per turn — separate for prefix caching)
        user_parts = []
        if conv_history:
            user_parts.append("## 对话记录")
            for msg in conv_history:
                user_parts.append(f"{msg['agent_name']}：{msg['content']}")
            user_parts.append("")
        user_parts.append("## 刚刚发生的")
        user_parts.append(f"{user_name}说：{req.message}")
        user_content = "\n".join(user_parts)

        # Run all agents in parallel
        async def get_reaction(aid: str) -> AgentReaction | None:
            ctx = target_contexts[aid]
            profile = ctx["_profile"]

            # Filter relationships to scene participants only
            participant_ids = {req.user_agent_id, *req.target_agent_ids}
            scene_rels = [r for r in ctx["relationships"] if r["target_id"] in participant_ids]

            system_prompt = render("role_play.j2", **{
                **ctx,
                "relationships": scene_rels,
            })

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

            result = await structured_call(
                response_model=AgentReactionLLM,
                messages=messages,
                temperature=0.9,
                max_tokens=1024,
            )
            llm_output: AgentReactionLLM = result.data
            return AgentReaction(
                agent_id=aid,
                agent_name=profile.name,
                **llm_output.model_dump(),
            )

        tasks = [asyncio.create_task(get_reaction(aid)) for aid in req.target_agent_ids]

        for coro in asyncio.as_completed(tasks):
            try:
                reaction = await coro
                if reaction and reaction.action != "silence":
                    yield {"data": json.dumps(
                        reaction.model_dump(), ensure_ascii=False
                    )}
            except ContextWindowExceededError:
                yield {"data": json.dumps({"error": _TOKEN_LIMIT_MSG}, ensure_ascii=False)}
            except Exception as e:
                yield {"data": json.dumps({"error": str(e)}, ensure_ascii=False)}

        yield {"data": json.dumps({"done": True})}

    return EventSourceResponse(event_generator())


# --- Share cards ------------------------------------------------------------


def _cd_header(filename_cjk: str) -> str:
    """RFC 5987 Content-Disposition for CJK filenames.

    Safari + some older Chrome builds mojibake raw UTF-8 in the `filename=`
    token; the `filename*=UTF-8''...` form is the only portable way to carry a
    Chinese filename through. The ASCII fallback is for ancient UAs that
    ignore `filename*`.
    """
    ascii_fallback = "simcampus_card.png"
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename_cjk, safe='')}"
    )


def _resolve_scene_group_index(
    scene_data: dict, group_index: int | None
) -> int:
    """Pick which group the share card should feature.

    Caller-supplied `group_index` wins when valid (in range, multi-agent, has
    ticks) — this is how the narrative UI shares the group the viewer is
    actually looking at. Otherwise fall back to the server's featured pick.
    Raises 404 HTTPException with a user-facing reason on any failure.
    """
    if group_index is not None:
        groups = scene_data.get("groups", [])
        if group_index < 0 or group_index >= len(groups):
            raise HTTPException(status_code=404, detail="该组不存在")
        group = groups[group_index]
        if group.get("is_solo") or len(group.get("participants", [])) < 2:
            raise HTTPException(
                status_code=404, detail="独白组没有场景卡，请切到多人组"
            )
        if not group.get("ticks"):
            raise HTTPException(status_code=404, detail="该组无内容")
        return group_index
    featured = scene_card.select_featured_group(scene_data)
    if featured is None:
        raise HTTPException(status_code=404, detail="该场景无对话，不生成场景卡")
    return featured


def _scene_meta(day: int, scene_idx: int, group_index: int | None = None) -> dict:
    """Compute caption/hashtags/filename from the scene LayoutSpec.

    Raises 404 HTTPException if no renderable group is available.
    """
    scene_data = scene_card.load_scene_by_array_index(day, scene_idx)
    gi = _resolve_scene_group_index(scene_data, group_index)
    spec = scene_card.scene_to_layout_spec(scene_data, gi)
    # Motif emoji from the strongest speaker, if we found one.
    motif_emoji = ""
    if spec.bubbles:
        from ..cards.assets import load_visual_bible  # local import, avoid cycle
        bible = load_visual_bible()
        motif_emoji = bible.get(spec.bubbles[0].agent_id, {}).get("motif_emoji", "")
    payload = card_captions.scene_caption(
        day=spec.day,
        scene_name=spec.scene_name,
        location=spec.location,
        time=spec.time,
        featured_quote=spec.featured_quote,
        featured_speaker=spec.featured_speaker_name,
        motif_emoji=motif_emoji,
    )
    payload["group_index"] = gi
    return payload


@app.get("/api/card/scene/{day}/{scene_idx}.png")
async def card_scene_png(
    day: int, scene_idx: int, group: int | None = None
) -> Response:
    try:
        scene_data = scene_card.load_scene_by_array_index(day, scene_idx)
    except (FileNotFoundError, IndexError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    gi = _resolve_scene_group_index(scene_data, group)
    # Cache key is per-group so different viewers' current-group shares don't
    # collide on the same scene key.
    key = f"scene_{day:03d}_{scene_idx}_g{gi}"

    def _render():
        spec = scene_card.scene_to_layout_spec(scene_data, gi)
        return scene_card._render_card(spec)

    path = card_cache.get_or_render(key, _render)
    meta = _scene_meta(day, scene_idx, group_index=gi)
    return Response(
        content=path.read_bytes(),
        media_type="image/png",
        headers={
            "Content-Disposition": _cd_header(meta["filename"]),
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/api/card/scene/{day}/{scene_idx}.json")
async def card_scene_meta(
    day: int, scene_idx: int, group: int | None = None
) -> dict:
    try:
        return _scene_meta(day, scene_idx, group_index=group)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IndexError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _daily_meta_and_caption(day: int) -> tuple[card_agg.DailySummary, dict]:
    try:
        summary = card_agg.build_daily_summary(day)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    headline = summary.headline
    cp = summary.cp
    caption = card_captions.daily_caption(
        day=day,
        headline_quote=headline.thought if headline else None,
        headline_speaker=(headline.thought_name or headline.speaker_name) if headline else None,
        cp_pair=(cp.a_name, cp.b_name) if cp else None,
    )
    return summary, caption


@app.get("/api/card/daily/{day}.png")
async def card_daily_png(day: int) -> Response:
    summary, caption = _daily_meta_and_caption(day)
    # v2: layout includes TopEvent / Contrast / ConcernSpotlight sections.
    # Bumping the key bypasses any `.cache/cards/daily_<day>.png` written by
    # the old renderer so deployments don't serve stale PNGs.
    key = f"daily_v2_{day:03d}"

    def _render():
        return daily_card._render_card(summary)

    path = card_cache.get_or_render(key, _render)
    return Response(
        content=path.read_bytes(),
        media_type="image/png",
        headers={
            "Content-Disposition": _cd_header(caption["filename"]),
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/api/card/daily/{day}.json")
async def card_daily_meta(day: int) -> dict:
    summary, caption = _daily_meta_and_caption(day)
    return {
        **card_agg.summary_to_dict(summary),
        "caption_payload": caption,
    }


def _build_agent_spec_and_caption(agent_id: str, day: int):
    world = _get_world()
    if agent_id not in world.agents:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")
    try:
        spec = agent_card.build_agent_spec(agent_id, day, world)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"unknown agent: {e}")
    caption = card_captions.agent_caption(
        day=day,
        agent_name_cn=spec.name_cn,
        motif_emoji=spec.motif_emoji,
        motif_tag=spec.motif_tag,
        emotion_label=spec.emotion_label,
        featured_quote=spec.featured_quote,
    )
    return spec, caption


@app.get("/api/card/agent/{agent_id}/{day}.png")
async def card_agent_png(agent_id: str, day: int) -> Response:
    spec, caption = _build_agent_spec_and_caption(agent_id, day)
    key = f"agent_{agent_id}_{day:03d}"

    def _render():
        return agent_card._render_card(spec)

    path = card_cache.get_or_render(key, _render)
    return Response(
        content=path.read_bytes(),
        media_type="image/png",
        headers={
            "Content-Disposition": _cd_header(caption["filename"]),
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/api/card/agent/{agent_id}/{day}.json")
async def card_agent_meta(agent_id: str, day: int) -> dict:
    spec, caption = _build_agent_spec_and_caption(agent_id, day)
    return {**agent_card.spec_to_dict(spec), "caption_payload": caption}


def run():
    uvicorn.run("sim.api.server:app", host="0.0.0.0", port=8000, reload=True)

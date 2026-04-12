import random

from ..models.event import Event, EventQueue


class EventQueueManager:
    def __init__(self, event_queue: EventQueue, rng: random.Random | None = None):
        self.eq = event_queue
        self.rng = rng or random.Random()

    def add_event(
        self,
        text: str,
        category: str,
        source_scene: str,
        source_day: int,
        witnesses: list[str],
        spread_probability: float = 0.5,
        cite_ticks: list[int] | None = None,
        group_index: int | None = None,
    ) -> Event:
        event_id = f"evt_{self.eq.next_id}"
        event = Event(
            id=event_id,
            source_scene=source_scene,
            source_day=source_day,
            text=text,
            category=category,
            witnesses=witnesses,
            known_by=list(witnesses),
            spread_probability=spread_probability,
            cite_ticks=list(cite_ticks) if cite_ticks else [],
            group_index=group_index,
        )
        self.eq.events.append(event)
        self.eq.next_id += 1
        return event

    def get_active_events_for_group(self, group_agent_ids: list[str]) -> list[Event]:
        """Find active events where someone in the group knows it but others don't."""
        spreadable: list[Event] = []
        for event in self.eq.events:
            if not event.active:
                continue
            knowers = set(event.known_by) & set(group_agent_ids)
            non_knowers = set(group_agent_ids) - set(event.known_by)
            if knowers and non_knowers:
                # Roll for spread
                if self.rng.random() < event.spread_probability:
                    spreadable.append(event)
        return spreadable

    def get_known_events(self, agent_id: str) -> list[Event]:
        """Get all active events known by this agent."""
        return [e for e in self.eq.events if e.active and agent_id in e.known_by]

    def mark_discussed(self, event_id: str, new_knowers: list[str]) -> None:
        for event in self.eq.events:
            if event.id == event_id:
                for agent_id in new_knowers:
                    if agent_id not in event.known_by:
                        event.known_by.append(agent_id)
                break

    def expire_old_events(self, current_day: int, expire_days: int = 3) -> None:
        for event in self.eq.events:
            if event.active and (current_day - event.source_day) >= expire_days:
                event.active = False

import neo
from pathlib import Path

path = Path("TENSS26_Anzal/2026-06-21_17-54-56")
reader = neo.io.get_io(str(path))
block = reader.read_block()

print(f"Loaded block with {len(block.segments)} segments")
for seg_idx, segment in enumerate(block.segments):
    print(f"Segment {seg_idx} has {len(segment.events)} events")
    for ev_idx, event in enumerate(segment.events):
        print(f"  Event {ev_idx}: {event.name}, {len(event.times)} times, labels: {len(event.labels)}")
        if len(event.times) > 0:
            print(f"    First 5 times: {event.times[:5]}")
            print(f"    First 5 labels: {event.labels[:5]}")

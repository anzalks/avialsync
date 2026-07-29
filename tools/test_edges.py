from pathlib import Path

from avialview.engine.sync_worker import SignalEvidenceSpec, SyncWorker

cache_dir = Path("TENSS26_Anzal/2026-06-21_17-54-56.avialcache")

ref_spec = SignalEvidenceSpec(
    source_id="2026-06-21_17-54-56",
    channel_id="Evt-Acquisition Board TTL Input",
    cache_dir=cache_dir,
    threshold=0.5,
)
ref_times = SyncWorker._event_times(ref_spec, use_all_times=False)

print(f"Edges extracted: {len(ref_times)}")

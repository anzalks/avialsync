from avialview.core.timeline import MasterClock

clock = MasterClock()
clock.t_min = 1700000000.0
clock.t_max = 1700000060.0
clock.t_current = 1700000005.0

print(clock.format_time(1700000005.0))
print(clock.format_time(1700000005.0, relative=False))

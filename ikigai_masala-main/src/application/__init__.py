"""Application layer — orchestration that is neither HTTP nor pure domain.

`api/app.py` had grown to 2,200 lines of which only ~43% was actually HTTP; the
rest was this: resolving client pins, working out a plan's horizon, assembling
the cooldown context, shaping saved plans for display. Those change for different
reasons than a route does and need no Flask to test, so they live here.
"""

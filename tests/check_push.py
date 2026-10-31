"""TASK 56 diagnostic: ONLY the push phase, both players (check_breakables.py runs it after its other
phases). Temporary helper for tuning; the proof is check_breakables.py itself.
Usage: python -I check_push.py <host pid> <guest pid>   (after a runner loaded the pair)
"""
import sys, os, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot
from peek import Proc
import check_breakables as cb


def main():
    hp, gp = int(sys.argv[1]), int(sys.argv[2])
    mh, mg = Proc(hp), Proc(gp)
    ph, pg = bot.Pipe(hp), bot.Pipe(gp)
    t = time.time()
    while time.time() - t < 90 and not (cb.world(mh) and cb.mode(mh) == 1 and cb.world(mg) and cb.mode(mg) == 1):
        time.sleep(0.5)
    time.sleep(2)
    if not cb.task53_level(mh, mg, ph, pg):
        print('push-only: J002 not reached')
        return 1
    h = cb.hpos(mh, cb.ctl_human(mh, 0))
    print('push-only: host player at (%.1f,%.1f,%.1f), %d whole props on the host copy, %d on the guest'
          % (h + (len(cb.usable_like(mh)), len(cb.usable_like(mg)))))
    fails = cb.task53_push(mh, mg, ph, pg)
    print('push-only: sync host  %s' % ph.cmd('sync'))
    print('push-only: sync guest %s' % pg.cmd('sync'))
    if fails:
        print('push-only FAIL:')
        for f in fails:
            print('  - ' + f)
        return 1
    print('push-only OK (3 pushes each way, >= %.0f units each, copies within %.0f)' % (cb.PUSH_MIN, cb.PUSH_AGREE))
    return 0


sys.exit(main())

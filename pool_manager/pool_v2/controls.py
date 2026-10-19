"""An operator pause cannot enable capabilities disabled by deployment settings."""

from contextlib import nullcontext
import re

from .database import lock
from .money import Conflict, FundsError

CHALLENGE_ID = re.compile(r'^[a-z0-9_]{1,32}$')


def paused(database, *, cursor=None):
    with (database.transaction() if cursor is None else nullcontext(cursor)) as query:
        query.execute("SELECT value FROM runtime_controls WHERE name='new_work_paused'")
        row=query.fetchone()
        return bool(row and row['value'])


def blocked(database,*,cursor=None):
    from .chain_observer import status
    from . import funding, spending
    if paused(database,cursor=cursor):return 'operator-pause'
    with (database.transaction() if cursor is None else nullcontext(cursor)) as query:
        reason=spending.blocked(query)
    if reason:return reason
    custody=status(database,cursor=cursor)
    if custody['initialized'] and not custody['ready']:return 'custody-reconciliation'
    protocol=funding.status(database,cursor=cursor)
    if protocol['initialized'] and not protocol['ready']:return 'protocol-fee-reconciliation'
    return None


def offered_challenges(database, *, cursor=None):
    """Sorted challenge ids the operator offers, or None while no list has been saved (every active challenge)."""
    with (database.transaction() if cursor is None else nullcontext(cursor)) as query:
        query.execute("SELECT name,value FROM runtime_controls WHERE name LIKE 'offer:%' ORDER BY name")
        rows = query.fetchall()
    if not rows:
        return None
    return [row['name'][6:] for row in rows if row['value']]


def set_offered_challenges(database, challenges, *, actor, reason, event_key, allowed=None):
    """Record which challenges members may receive; one audited event per challenge under the budget fence."""
    if (not isinstance(challenges, list) or len(set(challenges)) != len(challenges)
            or any(type(item) is not str or not CHALLENGE_ID.match(item) for item in challenges)):
        raise FundsError('offered challenges must be a list of distinct challenge ids')
    if not actor or not reason or not event_key:
        raise FundsError('offered challenge changes require an operator, reason and event key')
    wanted = sorted(challenges)
    if allowed is not None:
        missing = sorted(set(wanted) - set(allowed))
        if missing:
            raise FundsError('no runtime image is pinned for ' + ', '.join(missing))
    with database.transaction() as cursor:
        # Reservations read the list under this same fence, so a change never splits a selection.
        lock(cursor, 'operator:protocol-budget')
        cursor.execute("SELECT name,value FROM runtime_controls WHERE name LIKE 'offer:%' ORDER BY name")
        current = {row['name'][6:]: row['value'] for row in cursor.fetchall()}
        planned = {name: name in wanted for name in sorted(set(current) | set(wanted) | set(allowed or ()))}
        cursor.execute("SELECT name,after_value,actor,reason FROM runtime_control_events WHERE left(event_key,length(%s)+1)=%s",
                       (event_key, event_key + ':'))
        replay = cursor.fetchall()
        if replay:
            recorded = {row['name'][6:]: row['after_value'] for row in replay}
            if recorded != planned or any((row['actor'], row['reason']) != (actor, reason) for row in replay):
                raise Conflict('control event key was reused')
            return {'offered': offered_challenges(database, cursor=cursor), 'events': []}
        events = []
        for challenge, value in planned.items():
            cursor.execute("""INSERT INTO runtime_controls(name,value) VALUES (%s,%s)
                ON CONFLICT (name) DO UPDATE SET value=excluded.value,updated_at=clock_timestamp()""", ('offer:' + challenge, value))
            cursor.execute("""INSERT INTO runtime_control_events(event_key,name,before_value,after_value,actor,reason)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
                (event_key + ':' + challenge, 'offer:' + challenge, current.get(challenge, False), value, actor, reason))
            events.append(dict(cursor.fetchone()))
        return {'offered': offered_challenges(database, cursor=cursor), 'events': events}


def catalogue(database, *, manifest=None, offered_resources=('CPU',)):
    """What the operator chooses from: pinned runtime images, the current block's challenge families, the saved list."""
    from .block_observer import BlockStore
    from .protocol import ProtocolDataError
    images = dict((manifest or {}).get('runtime_images') or {})
    snapshot = None
    with database.transaction() as cursor:
        cursor.execute("SELECT id FROM observed_blocks ORDER BY height DESC LIMIT 1")
        row = cursor.fetchone()
    if row:
        try:
            snapshot = BlockStore(database).read(row['id'])[1]
        except ProtocolDataError:
            snapshot = None
    current = offered_challenges(database)
    known = snapshot.challenges if snapshot else {}
    rows = []
    for challenge_id in sorted(set(images) | set(known)):
        challenge = known.get(challenge_id)
        family = (str(challenge['config'].get('type') or '').upper() or None) if challenge else None
        image = images.get(challenge_id)
        match = re.search(r'tig-monorepo/([a-z_]+)/runtime', image or '')
        tracks = len(challenge['config'].get('active_tracks') or {}) if challenge else 0
        try:
            active = bool(challenge) and int(challenge['state']['round_active']) <= snapshot.round and tracks > 0
        except (KeyError, TypeError, ValueError):
            active = False
        rows.append({'id': challenge_id, 'name': match.group(1) if match else None, 'resource': family,
                     'active': active, 'tracks': tracks, 'runtime_image': image is not None,
                     'resource_offered': (family in offered_resources) if family else None,
                     'offered': None if current is None else challenge_id in current})
    return {'restricted': current is not None, 'offered': current, 'challenges': rows,
            'block_height': snapshot.height if snapshot else None}


def set_pause(database,value,*,actor,reason,event_key):
    if type(value) is not bool or not actor or not reason or not event_key:
        raise FundsError('pause changes require an operator, reason and event key')
    with database.transaction() as cursor:
        # Reservations and first precommit sends take this same budget fence.
        lock(cursor,'operator:protocol-budget')
        cursor.execute('SELECT * FROM runtime_control_events WHERE event_key=%s',(event_key,))
        previous=cursor.fetchone()
        if previous:
            if (previous['after_value'],previous['actor'],previous['reason'])!=(value,actor,reason):
                raise Conflict('control event key was reused')
            return dict(previous)
        before=paused(database,cursor=cursor)
        cursor.execute("""INSERT INTO runtime_controls(name,value) VALUES ('new_work_paused',%s)
            ON CONFLICT (name) DO UPDATE SET value=excluded.value,updated_at=clock_timestamp()""",(value,))
        cursor.execute("""INSERT INTO runtime_control_events(event_key,name,before_value,after_value,actor,reason)
            VALUES (%s,'new_work_paused',%s,%s,%s,%s) RETURNING *""",(event_key,before,value,actor,reason))
        return dict(cursor.fetchone())

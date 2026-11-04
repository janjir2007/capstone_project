"""Messenger km bot (task 9.15a): the driver writes his plate + km, the bot asks «Зөв үү?», saves the reading.

parse.py   message text -> (plate, km) or None (pure)
texts.py   the bot's Mongolian replies (one place to change wording)
send.py    Send API client (Graph API) + a fake for tests
flow.py    one webhook event -> database changes + replies
cleanup.py daily cleanup of old seen ids and expired pending questions
logs.py    keeps the verify token and PSIDs out of the logs
"""

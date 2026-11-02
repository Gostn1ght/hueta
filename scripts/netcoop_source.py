"""netcoop.cpp as the compiler sees it: its section includes inlined (doc 151)."""
from pathlib import Path

SECTIONS = ('netcoop_client.inc', 'netcoop_accounts.inc', 'netcoop_auth.inc', 'netcoop_events.inc', 'netcoop_trade.inc', 'netcoop_dialogue.inc', 'netcoop_tasks.inc', 'netcoop_task_list.inc', 'netcoop_task_list_client.inc', 'netcoop_news.inc', 'netcoop_script_messages.inc', 'netcoop_net_sync.inc', 'netcoop_corpse_drag.inc', 'netcoop_rp_anims.inc')


def netcoop_cpp(root, encoding='utf-8', errors='strict'):
    game = Path(root) / 'src' / 'xrGame'
    text = (game / 'netcoop.cpp').read_text(encoding=encoding, errors=errors)
    for name in SECTIONS:
        line = '#include "' + name + '"'
        part = (game / name).read_text(encoding=encoding, errors=errors)
        if encoding == 'utf-8-sig' or encoding == 'utf-8':
            part = part.lstrip('\ufeff')
        text = text.replace(line, part, 1)
    return text

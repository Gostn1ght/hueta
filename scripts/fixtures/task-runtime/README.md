# GAMMA task runtime fixtures

Extracted from the deployed GAMMA server scripts (existing project dependency).
The Lua functions retain upstream authorship; they are not replacements for the game scripts.

Original decoded-as-CP1251, UTF-8 re-encoded SHA256:
- task_manager.script: 5dee26dd7ea86ee212d61aa6abe7a16f4a5f60b9fce926735d4cf094c2f656e5
- task_objects.script: 8ec7c8fea9bb24e9984088c1955aa1e402173af3a195b9dfdc52ed763b59304f

`task_callback`, `task_complete`, `update`, `give_reward`, `save_load`, and
`object_save_load` contain the real upstream functions. `reward_constructor`
is a narrowed constructor fixture retaining the original reward field reads,
including the reward_item/reward_money typo, with unrelated UI/world setup omitted.
The test stubs engine objects, native task callbacks, inventory ownership and
condlist execution; it does not replace a real two-client/map integration test.

# Moving From An Earlier Version

Versions up to 2026.9.11 ran a full set of services on every computer and kept
their own copies of agent sessions. 2026.11.23 is a rebuild
([why](Why-A-Rebuild.md)); the earlier versions' own update button cannot
install it, so nothing gets overwritten by accident. Those from 2026.7.11 on may
show that a new version exists, but the update installs nothing.

Per computer, after the [server](Getting-Started.md) is up:

1. Give an agent on that computer the sentence from **Devices**. It installs
   the client and connects itself.
2. `tl.py old-install scan` lists the earlier install folders, their services
   and the history collections they kept, each with a ready `import` command.
   Each agent imports the collections that are its own. Imported history is
   held on the server until you start it on **Import** (the page shows the
   expected token use first).
3. `tl.py old-install stop` stops the earlier services.
4. Each agent removes its own settings that point into the earlier folder
   (MCP entries, prompt hooks, the earlier skill).
5. `tl.py old-install archive --to <folder>` keeps a copy of each earlier
   folder as a tar file and reads it back to check it.
6. `tl.py old-install remove` stops and removes the earlier services and
   folders. It refuses while a folder has no checked copy.

To go back, the earlier releases remain on the
[releases page](https://github.com/strmforge/time-library/releases).

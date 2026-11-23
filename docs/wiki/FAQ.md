# FAQ

**Is it another chat app?**
No. You keep working in your agents; Time Library collects, distills, and hands
memories back when they are needed.

**Do I need a NAS?**
Any x86-64 (Intel/AMD) machine that runs Docker and stays on will do; there is
no ARM image yet. The server is meant for your
home network: plain HTTP with a token per computer. Do not expose it to the
internet as it is.

**Which agents can connect?**
Any agent that can run commands and can describe its own session files (JSON
lines, zstd-compressed JSON lines, one JSON document per session, or SQLite).
There is nothing to wait for: see [Connecting An Agent](Connecting-An-Agent.md).

**What leaves my computer?**
The dialogue only. Tool calls, tool output, reasoning and injected context are
dropped on the computer. Credentials are always masked; email, phone and ID
numbers are masked by default.

**What is sent to a model?**
The dialogue being distilled, organised or answered from, to the endpoint you
chose for that task. A relay is a third party; the built-in local model keeps
everything on the NAS.

**What if the NAS is off, or gets a new address?**
The client keeps its read position and resumes; the agents' own session files
are the buffer. If the NAS's address changes, the client finds the server it
was paired with again on your home network.

**What if a model runs out of balance?**
The task moves to its backup or waits, and is retried by itself; nothing is
distilled twice.

**I forgot the admin password.**
On the sign-in page, click **Forgot the password?** and give the server key:
the line in `admin_token.txt` in the server's `data/` folder.

**How do I update?**
On **Overview**, click **Update to …** when there is a newer version: only the
server's own program is fetched (under 1 MB), not the image, and a version that
does not work is gone back from by itself. Clients follow the server's version
by themselves.

**Where did the earlier version's features go?**
See [Why A Rebuild](Why-A-Rebuild.md). Its history can be brought over:
[Moving From An Earlier Version](Moving-From-An-Earlier-Version.md).

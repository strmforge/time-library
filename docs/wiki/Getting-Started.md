# Getting Started

## 1. Server

On a NAS or Linux box with Docker, in a folder on its own disk (not a network
share: it holds a SQLite database):

```bash
mkdir -p time-library && cd time-library
curl -fLO https://raw.githubusercontent.com/strmforge/time-library/main/deploy/nas/docker-compose.yml
docker compose up -d
```

Open `http://<nas-address>:9850`, set the admin password, then on **Models**
add a source (address + protocol + key, pull its model list, test) or switch on
the built-in local model, and pick a model for **Daily distillation**. The admin
is in English and Chinese (switch it with the language button).

## 2. Agents

On **Devices**, click **Make a pairing sentence** and give the sentence to an
agent on the computer you want to connect. The agent follows `/client/install.md`
on the server:

1. unpack the client together with its own Python into `~/.time-library-client`
   (one `curl | tar`; Windows 10+ uses its own `curl.exe` and `tar.exe`);
2. `tl.py pair` with the token (once per computer);
3. describe its own session files, try the description with `tl.py check` on
   its own files until it looks right, then `tl.py report-agent` with it and
   what it supports (MCP, skill, prompt hook) — see
   [Connecting An Agent](Connecting-An-Agent.md);
4. `tl.py service install` (once per computer): uploads keep running after login;
5. connect what it has: the `time-library` MCP server, the skill, the prompt hook.

For another agent on the same computer, use **Connect another agent** on the
Devices page: same steps without pairing.

## 3. What happens next

- Dialogue appears on **Overview** within seconds of a conversation.
- Every night at 02:00 (NAS time) new dialogue is distilled into memories.
  **Memory** shows each with its original words, who borrowed it, and how it
  was judged.
- History from before you installed can be brought in with `tl.py import`;
  it waits on **Import** until you choose a range and start it.

## Updating

- Server: `docker compose pull && docker compose up -d` in the same folder.
  Everything it keeps is in `data/`.
- Clients follow the server's version by themselves.

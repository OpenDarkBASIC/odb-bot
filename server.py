import os
import sys
import json
import hmac
import hashlib
import traceback
import asyncio
import quart
from discord.ext import commands


if not os.path.exists("config.json"):
    open("config.json", "wb").write(json.dumps({
        "discord": {
            "prefix": ".",
            "token": "",
            "channel_id": 0
        },
        "github": {
            "secret": "",
            "port": 8013
        }
    }, indent=2).encode("utf-8"))
    print("Created file config.json. Please edit it with the correct token now, then run the bot again")
    sys.exit(1)


config = json.loads(open("config.json", "rb").read().decode("utf-8"))
bot = commands.Bot(command_prefix=config["discord"]["prefix"])
app = quart.Quart(__name__)


def ping(data):
    return "github ping"

def create(data):
    return None


github_handlers = {
    "ping": ping,
    "create": create
}


def verify_signature(payload, github_signature):
    payload_signature = hmac.new(
            key=config["github"]["secret"].encode("utf-8"),
            msg=payload,
            digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(payload_signature, github_signature)


@app.route("/github", methods=["POST"])
async def hello():
    payload = await quart.request.get_data()
    if not verify_signature(payload, quart.request.headers["X-Hub-Signature-256"].replace("sha256=", "")):
        quart.abort(403)

    channel = bot.get_channel(config["discord"]["channel_id"])
    if channel is None:
        return ""

    try:
        discord_msg = github_handlers[quart.request.headers["X-GitHub-Event"]](json.loads(payload.decode("utf-8")))
    except KeyError:
        # No handler for this event exists, so response with a generic one
        discord_msg = "Unhandled github event: {}".format(quart.request.headers["X-GitHub-Event"])
    except Exception as e:
        discord_msg = f"```{e}```"

    if discord_msg is not None:
        await channel.send(discord_msg)
    return ""


@bot.command(name="ping")
async def ping(ctx):
    await ctx.send("pong")


loop = asyncio.get_event_loop()
try:
    loop.create_task(bot.start(config["discord"]["token"]))
    app.run(loop=loop, port=config["github"]["port"])
except KeyboardInterrupt:
    loop.run_until_complete(bot.logout())
except:
    traceback.print_exc()
    loop.run_until_complete(bot.logout())
finally:
    loop.close()


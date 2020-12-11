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
    return "(github ping)"

def create(data):
    ref_type = data["ref_type"]
    ref = data["ref"]
    user = data["sender"]["login"]
    repo = data["repository"]["name"]

    return f"{user} created {ref_type} `{ref}` for repo {repo}"

def delete(data):
    ref_type = data["ref_type"]
    ref = data["ref"]
    user = data["sender"]["login"]
    repo = data["repository"]["name"]

    return f"{user} deleted {ref_type} `{ref}` for repo {repo}"

def issues(data):
    action = data["action"]
    number = data["issue"]["number"]
    user = data["issue"]["user"]["login"]
    title = data["issue"]["title"]

    if action == "opened":
        url = data["issue"]["html_url"]
        return f"{user} opened new issue #{number} (<{url}>) ```{title}```"
    elif action in ("reopened", "closed", "edited"):
        url = data["issue"]["html_url"]
        return f"{user} {action} issue #{number} (<{url}>) ```{title}```"
    elif action == "deleted":
        return f"{user} deleted issue #{number} ```{title}```"

def issue_comment(data):
    action = data["action"]
    user = data["comment"]["user"]["login"]
    url = data["issue"]["html_url"]
    number = data["issue"]["number"]
    title = data["issue"]["title"]

    return f"{user} {action} comment on issue #{number} (<{url}>) ```{title}```"

def push(data):
    commit_msgs = [x["message"] for x in data["commits"]]
    if len(commit_msgs) > 0:
        commit_msgs = "\n".join(" * " + x for x in commit_msgs)
        if len(commit_msgs) > 800:
            return f"{data['pusher']['name']} pushed a whole bunch of shit to branch `{data['ref']}` (too much to list)"
        else:
            return f"{data['pusher']['name']} pushed to branch `{data['ref']}` ```\n{commit_msgs}```"
    return f"{data['pusher']['name']} pushed to branch `{data['ref']}` ```\n * {data['head_commit']['message']}```"

def fork(data):
    user = data["sender"]["login"]
    repo = data["repository"]["name"]
    url = data["forkee"]["html_url"]

    return f"{user} forked repo {repo} (<{url}>)"

def commit_comment(data):
    return None

def pull_request(data):
    action = data["action"]
    number = data["number"]
    repo = data["repository"]["name"]
    user = data["sender"]["login"]
    url = data["pull_request"]["html_url"]
    title = data["pull_request"]["title"]

    map_action = {
        "opened": "opened",
        "edited": "edited",
        "closed": "closed",
        "review_requested": "requested a review on",
        "review_request_removed": "removed request for a review on",
        "ready_for_review": "is ready for review on",
        "locked": "locked",
        "unlocked": "unlocked",
        "reopened": "reopened"
    }

    if action in ("labeled", "unlabeled", "synchronize", "assigned", "unassigned"):
        return None

    if action == "closed":
        if data["pull_request"]["merged"]:
            branch = data["pull_request"]["base"]["ref"]
            return f"{user} merged PR #{number} into branch {branch} ```{title}```"

    return f"{user} {map_action['action']} PR #{number} (<{url}>) ```{title}```"

def pull_request_review(data):
    return None

def pull_request_review_comment(data):
    return None

def star(data):
    action = data["action"]
    repo = data["repository"]["name"]
    user = data["sender"]["login"]
    star_count = data["repository"]["stargazers_count"]

    if action == "created":
        return f"{user} starred repo {repo} ({star_count} stars total)"
    if action == "deleted":
        return f"{user} unstarred repo {repo} ({star_count} stars total)"

def watch(data):
    repo = data["repository"]["name"]
    user = data["sender"]["login"]
    watch_count = data["repository"]["watchers_count"]

    return f"{user} watched repo {repo} ({watch_count} watches total)"


github_handlers = {
    "ping": ping,
    "create": create,
    "delete": delete,
    "issues": issues,
    "issue_comment": issue_comment,
    "push": push,
    "fork": fork,
    "commit_comment": commit_comment,
    "issue_comment": issue_comment,
    "pull_request": pull_request,
    "pull_request_review": pull_request_review,
    "pull_request_review_comment": pull_request_review_comment,
    "star": star,
    "watch": watch
}


def verify_signature(payload, github_signature):
    payload_signature = hmac.new(
            key=config["github"]["secret"].encode("utf-8"),
            msg=payload,
            digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(payload_signature, github_signature)


@app.route("/github", methods=["POST"])
async def github_event():
    print("github_event")
    payload = await quart.request.get_data()
    if not verify_signature(payload, quart.request.headers["X-Hub-Signature-256"].replace("sha256=", "")):
        quart.abort(403)

    channel = bot.get_channel(config["discord"]["channel_id"])
    if channel is None:
        return ""

    event_type = quart.request.headers["X-GitHub-Event"]
    try:
        handler = github_handlers[event_type]
    except KeyError:
        # No handler for this event exists, so response with a generic one
        print(f"No handler found")
        await channel.send("Unhandled github event: `{}`".format(event_type))
        return ""

    try:
        discord_msg = handler(json.loads(payload.decode("utf-8")))
    except Exception as e:
        traceback.print_exc()
        discord_msg = f"```{e}```"

    if discord_msg is not None:
        await channel.send(discord_msg)
    return ""


@app.route("/")
async def index():
    return "Hello!"


@bot.command(name="ping")
async def ping(ctx):
    await ctx.send("pong")


@bot.command(name="echo")
async def echo(ctx):
    try:
        msg = ctx.message.content.split(" ", 1)[1]
    except:
        return await ctx.send("Expected 1 argument")
    await ctx.send(msg)


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


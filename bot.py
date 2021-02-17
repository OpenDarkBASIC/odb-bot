import os
import sys
import json
import hmac
import hashlib
import traceback
import asyncio
import quart
import aiohttp
from discord.ext import commands


if not os.path.exists("config.json"):
    open("config.json", "wb").write(json.dumps({
        "discord": {
            "prefix": ".",
            "token": "",
            "github_channel_id": 0,
            "odbci_channel_id": 0
        },
        "github": {
            "secret": "",
            "host": "0.0.0.0",
            "port": 8013
        },
        "dbpc": {
            "windows": {
                "endpoints": {
                    "compile": "http://127.0.0.1:/compile"
                }
            }
        },
        "odbc": {
            "windows": {
                "endpoints": {
                    "compile": "http://127.0.0.1:/compile"
                },
            },
            "linux": {
                "endpoints": {
                    "compile": "http://127.0.0.1:/compile"
                }
            }
        },
        "odbci": {
            "endpoints": {
                "pull": "http://127.0.0.1:8016/pull_sources",
                "update": "http://127.0.0.1:8016/update_odb",
                "clear": "http://127.0.0.1:8016/clear_cache",
                "run": "http://127.0.0.1:8016/run_all",
                "status": "http://127.0.0.1:8016/status"
            }
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


def check_run(data):
    if not data["check_run"]["status"] == "completed":
        return None

    conclusion = data["check_run"]["conclusion"]
    if conclusion in ("failure", "timed_out", "action_required"):
        name = data["check_run"]["name"]
        repo = data["repository"]["name"]
        url = data["check_run"]["html_url"]
        map_conclusion = {
            "failure": "failed",
            "timed_out": "timed out",
            "action_required": "requires action"
        }
        return f"Check run {map_conclusion[conclusion]} for repo {repo} (<{url}>)"


def check_suite(data):
    if data["check_suite"]["status"] == "requested":
        branch = data["check_suite"]["head_branch"]
        user = data["sender"]["login"]
        repo = data["repository"]["name"]
        return f"{user} requested check suite for branch {branch} in repo {repo}"

    if data["check_suite"]["status"] == "completed":
        conclusion = data["check_suite"]["conclusion"]
        if conclusion in ("failure", "timed_out", "action_required"):
            repo = data["repository"]["name"]
            branch = data["check_suite"]["head_branch"]
            url = data["check_suite"]["url"]
            map_conclusion = {
                "failure": "failed",
                "timed_out": "timed out",
                "action_required": "requires action"
            }
            return f"Check suite for branch {branch} {map_conclusion[conclusion]} for repo {repo} (<{url}>)"

    return None


def label(data):
    return None


def milestone(data):
    return None


github_handlers = {
    "ping": ping,
    "create": create,
    "delete": delete,
    "issues": issues,
    "issue_comment": issue_comment,
    "push": push,
    "fork": fork,
    "commit_comment": commit_comment,
    "pull_request": pull_request,
    "pull_request_review": pull_request_review,
    "pull_request_review_comment": pull_request_review_comment,
    "star": star,
    "watch": watch,
    "check_run": check_run,
    "check_suite": check_suite,
    "label": label,
    "milestone": milestone
}


def verify_signature(payload, signature, secret):
    payload_signature = hmac.new(
            key=secret.encode("utf-8"),
            msg=payload,
            digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(payload_signature, signature)


def create_signature(payload, secret):
    payload_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256).hexdigest()
    return payload_signature


def get_dbp_source(msg):
    start = msg.find("```") + 3
    end = msg.rfind("```")
    if start > -1 and end > -1:
        msg = msg[start:end]
        if msg.startswith("basic"):
            msg = msg[6:]
        return msg

    start = msg.find("``") + 2
    end = msg.rfind("``")
    if start > -1 and end > -1:
        return msg[start:end]

    start = msg.find("`") + 1
    end = msg.rfind("`")
    if start > -1 and end > -1:
        return msg[start:end]

    return None


async def compile_dbp_code(compiler_name, platform, code):
    try:
        endpoint = config[compiler_name][platform]["endpoints"]["compile"]
    except KeyError:
        return f"Unknown compiler/platform: {compiler_name}/{platform}"

    try:
        async with aiohttp.ClientSession() as session:
            payload = json.dumps({
                "code": code
            }).encode("utf-8")
            async with session.post(url=endpoint, data=payload) as resp:
                if resp.status != 200:
                    return f"Endpoint {endpoint} returned {resp.status}"
                resp = await resp.read()
                resp = json.loads(resp.decode("utf-8"))
                return f"{compiler_name}/{platform}:```\n{resp['output']}```"
    except aiohttp.ClientError as e:
        return f"Failed to connect to endpoint {endpoint}: {e}"


@app.route("/github", methods=["POST"])
async def github_event():
    payload = await quart.request.get_data()
    if not verify_signature(payload, quart.request.headers["X-Hub-Signature-256"].replace("sha256=", ""), config["github"]["secret"]):
        quart.abort(403)

    channel = bot.get_channel(config["discord"]["github_channel_id"])
    if channel is None:
        return ""

    event_type = quart.request.headers["X-GitHub-Event"]
    try:
        handler = github_handlers[event_type]
    except KeyError:
        # No handler for this event exists, so response with a generic one
        await channel.send(f"Unhandled github event: `{event_type}`")
        return ""

    try:
        discord_msg = handler(json.loads(payload.decode("utf-8")))
    except Exception as e:
        traceback.print_exc()
        discord_msg = f"```{traceback.format_exc()}```"

    if discord_msg is not None:
        await channel.send(discord_msg)
    return ""


@app.route("/odb-dbp-ci/status", methods=["POST"])
async def odb_dbp_ci_status():
    payload = await quart.request.get_data()
    data = json.loads(payload.decode("utf-8"))
    channel = bot.get_channel(config["discord"]["odbci_channel_id"])
    if channel is None:
        return ""

    await channel.send(data["message"])
    return ""


@bot.command(name="dbpc")
async def dbpc(ctx):
    src = get_dbp_source(ctx.message.content)
    if src is None:
        return await ctx.send("``` dbpc `code` ```")

    result = await compile_dbp_code("dbpc", "windows", src)
    await ctx.send(result)


@bot.command(name="odbc")
async def odbc(ctx):
    src = get_dbp_source(ctx.message.content)
    if src is None:
        return await ctx.send("``` odbc [linux|windows] `code` ```")

    # Parse optional platform
    platform = "linux"
    try:
        maybe_platform = ctx.message.content.split(" ", 2)[1]
        if maybe_platform in ("windows", "linux"):
            platform = maybe_platform
    except IndexError:
        pass

    result = await compile_dbp_code("odbc", platform, src)
    await ctx.send(result)


@bot.command(name="odbci")
async def odbci(ctx):
    help_str = """```
odbci pull - Pull from sources repo
odbci update - Update ODB compilers
odbci clear - Discard any cached compile/run results 
odbci run - Run all tests
odbci status - Print summary of last run```"""
    args = ctx.message.content.split(" ")
    if len(args) == 1:
        return await ctx.send(help_str)

    try:
        endpoint = config["odbci"]["endpoints"][args[1]]
    except KeyError:
        return await ctx.send(help_str)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url=endpoint) as resp:
                if resp.status != 200:
                    return await ctx.send(f"Endpoint returned status {resp.status}")
        except aiohttp.ClientError as e:
            return await ctx.send(f"Failed to connect to endpoint {endpoint}: {e}")
        except Exception as e:
            return await ctx.send(f"Error occurred: {e}")


loop = asyncio.get_event_loop()
try:
    loop.create_task(bot.start(config["discord"]["token"]))
    app.run(loop=loop, host=config["github"]["host"], port=config["github"]["port"])
except KeyboardInterrupt:
    loop.run_until_complete(bot.logout())
except:
    traceback.print_exc()
    loop.run_until_complete(bot.logout())
finally:
    loop.close()

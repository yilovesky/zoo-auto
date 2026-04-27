import playwright_zo_flow as flow


class DummyLocator:
    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class DummyPage:
    def __init__(self, url_to_body):
        self.url_to_body = url_to_body
        self.url = ""

    async def goto(self, url, wait_until=None, timeout=None):
        self.url = url

    async def wait_for_load_state(self, state, timeout=None):
        return None

    def locator(self, selector):
        return DummyLocator(self.url_to_body[self.url])


def test_wait_for_workspace_rejects_public_site_false_positive():
    page = DummyPage(
        {
            "https://baico.zo.computer/": "Public page with Sign up",
            "https://app.zo.computer/": "Marketing copy with Ask Zo and Sign up",
            "https://www.zo.computer/app": "Public page also mentioning Agents and Projects",
            "https://www.zo.computer/": "Homepage with Ask Zo, Agents, Projects, and Sign up",
        }
    )
    assert flow.asyncio.run(flow.wait_for_workspace(page)) is False


def test_wait_for_workspace_accepts_real_app_url_with_workspace_markers():
    page = DummyPage(
        {
            "https://baico.zo.computer/": "首页\n文件\n聊天\n新聊天",
            "https://app.zo.computer/": "Ask Zo\nAgents\nProjects\nNew chat",
            "https://www.zo.computer/app": "unused",
            "https://www.zo.computer/": "unused",
        }
    )
    assert flow.asyncio.run(flow.wait_for_workspace(page)) is True


def test_wait_for_workspace_accepts_custom_workspace_host():
    page = DummyPage(
        {
            "https://baico.zo.computer/": "首页\n文件\n聊天\n新聊天",
            "https://app.zo.computer/": "unused",
            "https://www.zo.computer/app": "unused",
            "https://www.zo.computer/": "unused",
        }
    )
    assert flow.asyncio.run(flow.wait_for_workspace(page)) is True

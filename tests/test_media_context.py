from dataclasses import dataclass

from astrbot_plugin_ffmpeg.media_context import MediaContextManager


@dataclass
class FakeMedia:
    file: str = ""
    url: str = ""
    path: str = ""


class FakeEvent:
    def __init__(self, origin: str, messages: list[object], message_id: str = "m1", user_id: str = "u1"):
        self.unified_msg_origin = origin
        self.message_id = message_id
        self.user_id = user_id
        self._messages = messages

    def get_messages(self):
        return self._messages


class FakeReply:
    def __init__(self, chain):
        self.chain = chain


class FakeAstrBotFile:
    def __init__(self, url: str = "", file_: str = ""):
        self.url = url
        self.file_ = file_

    @property
    def file(self):
        raise AssertionError("File.file must not be accessed in async context")


def test_capture_media_keeps_per_session_items_and_stable_ids():
    manager = MediaContextManager(max_items_per_session=5)
    event = FakeEvent("group:1", [FakeMedia(file="file:///tmp/a.mp4")])

    captured = manager.capture_event_media(event)

    assert len(captured) == 1
    assert captured[0].media_id
    assert captured[0].session_id == "group:1"
    assert captured[0].source == "file:///tmp/a.mp4"
    assert manager.list_media(event)[0]["media_id"] == captured[0].media_id


def test_capture_media_trims_oldest_items_per_session():
    manager = MediaContextManager(max_items_per_session=2)

    first = manager.capture_event_media(FakeEvent("group:1", [FakeMedia(file="a.mp4")], "m1"))[0]
    second = manager.capture_event_media(FakeEvent("group:1", [FakeMedia(file="b.mp4")], "m2"))[0]
    third = manager.capture_event_media(FakeEvent("group:1", [FakeMedia(file="c.mp4")], "m3"))[0]

    items = manager.list_media(FakeEvent("group:1", []))
    assert [item["media_id"] for item in items] == [second.media_id, third.media_id]
    assert manager.get_media(FakeEvent("group:1", []), media_id=first.media_id) is None


def test_get_media_selects_latest_one_based_index_and_id():
    manager = MediaContextManager(max_items_per_session=5)
    event = FakeEvent("group:1", [FakeMedia(file="a.mp4")], "m1")
    first = manager.capture_event_media(event)[0]
    second = manager.capture_event_media(FakeEvent("group:1", [FakeMedia(file="b.mp4")], "m2"))[0]

    assert manager.get_media(event).media_id == second.media_id
    assert manager.get_media(event, index=1).media_id == first.media_id
    assert manager.get_media(event, index=-1).media_id == second.media_id
    assert manager.get_media(event, media_id=first.media_id).source == "a.mp4"


def test_sessions_are_isolated():
    manager = MediaContextManager(max_items_per_session=5)
    manager.capture_event_media(FakeEvent("group:1", [FakeMedia(file="a.mp4")]))
    manager.capture_event_media(FakeEvent("group:2", [FakeMedia(file="b.mp4")]))

    assert manager.get_media(FakeEvent("group:1", [])).source == "a.mp4"
    assert manager.get_media(FakeEvent("group:2", [])).source == "b.mp4"


def test_capture_ignores_non_media_components():
    manager = MediaContextManager(max_items_per_session=5)
    captured = manager.capture_event_media(FakeEvent("group:1", [object()]))
    assert captured == []
    assert manager.list_media(FakeEvent("group:1", [])) == []


def test_capture_media_inside_reply_chain():
    manager = MediaContextManager(max_items_per_session=5)
    event = FakeEvent("group:1", [FakeReply([FakeMedia(file="reply.mp4")])])

    captured = manager.capture_event_media(event)

    assert len(captured) == 1
    assert captured[0].source == "reply.mp4"


def test_capture_file_component_prefers_url_without_touching_sync_file_property():
    manager = MediaContextManager(max_items_per_session=5)
    event = FakeEvent("group:1", [FakeAstrBotFile(url="https://example.test/a.mp3")])

    captured = manager.capture_event_media(event)

    assert len(captured) == 1
    assert captured[0].source == "https://example.test/a.mp3"

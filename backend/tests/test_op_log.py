
from app.persistence.op_log import OpLogWriter

DOC_A = "doc-a"


class FakeBatchWriter:
    """Records every batch it's asked to write; can be told to fail."""

    def __init__(self, should_fail: bool = False) -> None:
        self.batches: list[list] = []
        self.should_fail = should_fail

    def __call__(self, batch: list) -> None:
        if self.should_fail:
            raise RuntimeError("simulated write failure")
        self.batches.append(list(batch))


def make_writer(monkeypatch, should_fail: bool = False) -> tuple[OpLogWriter, FakeBatchWriter]:
    writer = OpLogWriter()
    fake = FakeBatchWriter(should_fail=should_fail)
    monkeypatch.setattr(writer, "_write_batch", fake)
    return writer, fake


async def test_enqueue_does_not_call_the_callback_immediately(monkeypatch):
    writer, _ = make_writer(monkeypatch)
    fired = []
    writer.enqueue(doc_id=DOC_A, seq=1, payload=b"x", on_durable=lambda: fired.append(1))

    assert fired == []  # nothing durable yet — enqueue only buffers


async def test_flush_writes_the_batch_then_fires_callbacks_in_order(monkeypatch):
    writer, fake = make_writer(monkeypatch)
    fired = []
    writer.enqueue(doc_id=DOC_A, seq=1, payload=b"one", on_durable=lambda: fired.append(1))
    writer.enqueue(doc_id=DOC_A, seq=2, payload=b"two", on_durable=lambda: fired.append(2))

    await writer._flush_once()

    assert len(fake.batches) == 1  # one commit covering both ops
    assert len(fake.batches[0]) == 2
    assert fired == [1, 2]  # callbacks only run after the write completes


async def test_a_failed_batch_never_fires_any_callback(monkeypatch):
    writer, fake = make_writer(monkeypatch, should_fail=True)
    fired = []
    writer.enqueue(doc_id=DOC_A, seq=1, payload=b"x", on_durable=lambda: fired.append(1))

    await writer._flush_once()  # must not raise out of the flush loop

    assert fired == []  # no ack, no broadcast for an op that never committed


async def test_empty_pending_never_calls_write_batch(monkeypatch):
    writer, fake = make_writer(monkeypatch)

    await writer._flush_once()

    assert fake.batches == []


async def test_ops_enqueued_after_a_flush_form_the_next_batch(monkeypatch):
    """The real timing: new ops keep arriving while a previous batch is
    already committed. They must land in their own next batch, never get
    silently merged into, or lost around, the one already written."""
    writer, fake = make_writer(monkeypatch)

    writer.enqueue(doc_id=DOC_A, seq=1, payload=b"one", on_durable=lambda: None)
    await writer._flush_once()

    writer.enqueue(doc_id=DOC_A, seq=2, payload=b"two", on_durable=lambda: None)
    await writer._flush_once()

    assert [len(b) for b in fake.batches] == [1, 1]


async def test_stop_flushes_whatever_is_still_pending(monkeypatch):
    """stop() is the graceful-shutdown path only — see op_log.py's own
    docstring on why this is not the kill -9 guarantee, just the SIGTERM
    one. This test exercises the real start()/stop() task lifecycle, not
    just _flush_once() directly."""
    writer, fake = make_writer(monkeypatch)

    writer.start()
    fired = []
    writer.enqueue(doc_id=DOC_A, seq=1, payload=b"x", on_durable=lambda: fired.append(1))

    await writer.stop()

    assert len(fake.batches) == 1
    assert fired == [1]

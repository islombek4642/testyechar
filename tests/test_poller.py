import asyncio

from app.ai.poller import BatchPoller


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeStopDetails:
    def __init__(self, category):
        self.category = category


class FakeUsage:
    def __init__(self, input_tokens=0, output_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeMessage:
    def __init__(self, content, stop_reason="end_turn", stop_details=None, usage=None):
        self.content = content
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.usage = usage or FakeUsage()


class FakeResult:
    def __init__(self, type_, message=None, error=None):
        self.type = type_
        self.message = message
        self.error = error


class FakeIndividualResponse:
    def __init__(self, custom_id, result):
        self.custom_id = custom_id
        self.result = result


class FakeRequestCounts:
    def __init__(self, succeeded=0, errored=0, processing=0, canceled=0, expired=0):
        self.succeeded = succeeded
        self.errored = errored
        self.processing = processing
        self.canceled = canceled
        self.expired = expired


class FakeBatch:
    def __init__(self, processing_status, request_counts):
        self.processing_status = processing_status
        self.request_counts = request_counts


class FakeBatchesAPI:
    def __init__(self, batch, results):
        self._batch = batch
        self._results = results

    async def retrieve(self, batch_id):
        return self._batch

    async def results(self, batch_id):
        async def gen():
            for r in self._results:
                yield r

        return gen()


class FakeAnthropicClient:
    def __init__(self, batch, results):
        self.beta = type("B", (), {"messages": type("M", (), {"batches": FakeBatchesAPI(batch, results)})()})()


def _poller_with(batch, results) -> BatchPoller:
    poller = BatchPoller(api_key="test-key")
    poller.client = FakeAnthropicClient(batch, results)
    return poller


def test_poll_until_complete_returns_answers_and_no_warnings_when_all_succeed():
    batch = FakeBatch("ended", FakeRequestCounts(succeeded=1))
    results = [
        FakeIndividualResponse(
            "chunk-1",
            FakeResult(
                "succeeded",
                FakeMessage(
                    content=[FakeTextBlock('{"answers": [{"id": 1, "c": 0, "cf": 0.9}]}')],
                    usage=FakeUsage(input_tokens=500, output_tokens=50),
                ),
            ),
        ),
    ]
    poller = _poller_with(batch, results)

    answers, warnings, input_tokens, output_tokens = asyncio.run(
        poller.poll_until_complete("batch-1", interval_seconds=0)
    )

    assert len(answers) == 1
    assert answers[0].id == 1
    assert warnings == []
    assert input_tokens == 500
    assert output_tokens == 50


def test_poll_until_complete_reports_refusal_as_warning_not_parse_error():
    batch = FakeBatch("ended", FakeRequestCounts(succeeded=2, errored=1))
    results = [
        FakeIndividualResponse(
            "chunk-1",
            FakeResult(
                "succeeded",
                FakeMessage(
                    content=[FakeTextBlock('{"answers": [{"id": 1, "c": 0, "cf": 0.9}]}')],
                    usage=FakeUsage(input_tokens=500, output_tokens=50),
                ),
            ),
        ),
        FakeIndividualResponse(
            "chunk-2",
            FakeResult(
                "succeeded",
                FakeMessage(
                    content=[],
                    stop_reason="refusal",
                    stop_details=FakeStopDetails("dangerous_content"),
                    usage=FakeUsage(input_tokens=300, output_tokens=5),
                ),
            ),
        ),
        FakeIndividualResponse("chunk-3", FakeResult("errored", error="boom")),
    ]
    poller = _poller_with(batch, results)

    answers, warnings, input_tokens, output_tokens = asyncio.run(
        poller.poll_until_complete("batch-1", interval_seconds=0)
    )

    assert len(answers) == 1  # only chunk-1 contributes answers
    assert len(warnings) == 1
    assert "rad etildi" in warnings[0]
    assert "1 ta" in warnings[0]  # exactly the refused chunk, not the errored one
    # Refused chunk's usage still counts (Anthropic bills it) — errored chunk's doesn't.
    assert input_tokens == 800
    assert output_tokens == 55

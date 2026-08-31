from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.services import sentiment


class _FakeProbabilities:
    def __init__(self, values):
        self._values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self._values


class _FakeTorch:
    def __init__(self, probabilities):
        self._probabilities = probabilities

    def inference_mode(self):
        return nullcontext()

    def softmax(self, logits, dim):
        assert logits == "test-logits"
        assert dim == -1
        return _FakeProbabilities(self._probabilities)


class _FakeTokenizer:
    def __init__(self):
        self.calls = []

    def __call__(self, batch, **kwargs):
        self.calls.append((batch, kwargs))
        return {"input_ids": batch}


class _FakeModel:
    config = SimpleNamespace(
        id2label={0: "positive", 1: "negative", 2: "neutral"},
    )

    def __call__(self, **encoded):
        assert "input_ids" in encoded
        return SimpleNamespace(logits="test-logits")


def test_analyse_text_uses_direct_offline_model_inference(monkeypatch):
    tokenizer = _FakeTokenizer()
    model = _FakeModel()
    torch = _FakeTorch([[0.8, 0.1, 0.1]])
    monkeypatch.setattr(
        sentiment,
        "get_finbert_components",
        lambda: (tokenizer, model, torch),
    )

    result = sentiment.analyse_text("Revenue and profit increased.")

    assert result["sentiment_label"] == "positive"
    assert result["confidence_score"] == pytest.approx(0.8)
    assert result["distribution"] == {
        "positive": 0.8,
        "neutral": 0.1,
        "negative": 0.1,
    }
    assert result["chunks_analyzed"] == 1
    assert tokenizer.calls == [
        (
            ["Revenue and profit increased."],
            {
                "padding": True,
                "truncation": True,
                "max_length": 512,
                "return_tensors": "pt",
            },
        )
    ]


def test_predict_chunks_batches_inference(monkeypatch):
    tokenizer = _FakeTokenizer()
    model = _FakeModel()
    torch = _FakeTorch([[0.6, 0.2, 0.2], [0.1, 0.1, 0.8]])
    monkeypatch.setattr(sentiment, "FINBERT_BATCH_SIZE", 2)
    monkeypatch.setattr(
        sentiment,
        "get_finbert_components",
        lambda: (tokenizer, model, torch),
    )

    predictions = sentiment._predict_chunks(["first", "second"])

    assert [item[0]["score"] for item in predictions] == [0.6, 0.1]
    assert len(tokenizer.calls) == 1


def test_empty_text_does_not_load_finbert(monkeypatch):
    load = pytest.fail
    monkeypatch.setattr(sentiment, "get_finbert_components", load)

    assert sentiment.analyse_text("   ")["sentiment_label"] == "neutral"
    assert sentiment.analyse_text("   ")["chunks_analyzed"] == 0

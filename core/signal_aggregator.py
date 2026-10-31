from collections import defaultdict
from typing import Any


class SignalAggregator:
    """Birden fazla zaman dilimindeki sinyalleri tek karar halinde birleştirir."""

    def aggregate(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        if not signals:
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "timeframes": [],
                "signals": [],
            }

        valid_signals = []
        for signal in signals:
            if not isinstance(signal, dict):
                continue

            action = str(signal.get("action", signal.get("signal", "HOLD"))).upper()
            if action in {"HOLD", "NO_ACTION"}:
                continue

            timeframe = str(signal.get("timeframe", "unknown"))
            confidence = float(signal.get("confidence", 0.5))
            valid_signals.append({
                "action": action,
                "timeframe": timeframe,
                "confidence": max(0.0, min(confidence, 1.0)),
                "signal": signal,
            })

        if not valid_signals:
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "timeframes": [],
                "signals": [],
            }

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for signal in valid_signals:
            grouped[signal["action"]].append(signal)

        best_action = None
        best_group = []
        best_score = -1.0

        for action, items in grouped.items():
            weight = 0.0
            timeframes = []
            for item in items:
                timeframes.append(item["timeframe"])
                weight += item["confidence"]

            score = weight + (len(items) * 0.12)
            if score > best_score:
                best_score = score
                best_action = action
                best_group = items

        if best_action is None:
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "timeframes": [],
                "signals": [],
            }

        timeframes = [item["timeframe"] for item in best_group]
        mean_confidence = sum(item["confidence"] for item in best_group) / len(best_group)
        confidence = min(0.99, max(0.5, mean_confidence + (len(best_group) * 0.12)))

        if len(best_group) >= 2 and confidence >= 0.75:
            return {
                "action": best_action,
                "confidence": round(confidence, 4),
                "timeframes": timeframes,
                "signals": best_group,
                "confirmed": True,
            }

        if confidence >= 0.65:
            return {
                "action": best_action,
                "confidence": round(confidence, 4),
                "timeframes": timeframes,
                "signals": best_group,
                "confirmed": False,
            }

        return {
            "action": "HOLD",
            "confidence": 0.0,
            "timeframes": timeframes,
            "signals": best_group,
            "confirmed": False,
        }

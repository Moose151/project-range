"""Read-only CBM-400 EBEM polling via SSH/ICC command messages."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass


class CBMError(RuntimeError):
    pass


@dataclass
class CBMSnapshot:
    tx_config: dict[str, str]
    rx_config: dict[str, str]
    status: dict[str, str]

    @property
    def summary(self) -> dict[str, str | None]:
        tx_on = self.tx_config.get("TX_OP")
        tx_power = self.tx_config.get("TXIF_LVL") or self.status.get("TXIF_LVL")
        tx_freq = self.tx_config.get("TXIF_FRQ")
        rx_freq = self.rx_config.get("RXIF_FRQ")
        return {
            "tx_operation": tx_on,
            "tx_if_enabled": self.status.get("TXIF_EN") or self.status.get("TXIF_ENABLED") or self.status.get("TX_ON"),
            "ita_tx_status": self.status.get("ITT_STAT"),
            "tx_if_power_dbm": tx_power,
            "tx_if_frequency_khz": tx_freq,
            "rx_if_frequency_khz": rx_freq,
            "tx_modulation": self.tx_config.get("TX_MOD"),
            "tx_symbol_rate": self.tx_config.get("TX_SR"),
            "tx_code": self.tx_config.get("TX_CODE"),
            "rx_modulation": self.rx_config.get("RX_MOD"),
            "rx_symbol_rate": self.rx_config.get("RX_SR"),
            "rx_code": self.rx_config.get("RX_CODE"),
            "rx_level_dbm": self.status.get("RXIF_LVL"),
            "rx_ebno_db": (
                self.status.get("RX_EBNO")
                or self.status.get("EBNO")
                or self.status.get("EBN0")
                or self.status.get("EB_N0")
                or self.status.get("EB_NO")
            ),
            "rx_esno_db": self.status.get("RX_ESNO"),
            "rx_ber_estimate": (
                self.status.get("RX_BEREST")
                or self.status.get("RX_BER_EST")
                or self.status.get("RX_BER")
                or self.status.get("BEREST")
                or self.status.get("BER_EST")
                or self.status.get("BER")
                or self.status.get("BERT_BER")
            ),
            "modem_status": self.status.get("MDM_STAT"),
            "link_status": self.status.get("LINK_STAT"),
            "fault_status": self.status.get("FLT_STAT"),
        }


def parse_icc_response(text: str, command_name: str) -> dict[str, str]:
    """Parse `TX_CFG A=B,C=D` style ICC output into a dict.

    The EBEM shell echoes the query back before answering, e.g.::

        tx_cfg ?
        TX_CFG TX_OP=ON,TXIF_LVL=-10.00,...

    The command name is matched case-insensitively, so we must NOT lock onto the
    lowercase echo line (`tx_cfg ?`) — doing so corrupts the first real field. The
    lookahead requires the command name to be followed by a `KEY=` list, which only
    the response line has, so the echoed query is skipped. The response can wrap over
    several lines, so whitespace is collapsed before splitting on commas.
    """
    pattern = re.compile(
        rf"\b{re.escape(command_name)}\b\s+(?=[A-Za-z0-9_]+\s*=)(.*)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return {}
    payload = re.sub(r"\s+", "", match.group(1))
    result: dict[str, str] = {}
    for part in payload.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().upper()
        if key:
            result[key] = value
    return result


def _read_available(channel, timeout: float) -> str:
    end = time.monotonic() + timeout
    chunks: list[str] = []
    while time.monotonic() < end:
        if channel.recv_ready():
            chunks.append(channel.recv(65535).decode("utf-8", errors="replace"))
            end = time.monotonic() + 0.2
        else:
            time.sleep(0.05)
    return "".join(chunks)


def poll_cbm_ssh(host: str, username: str, password: str, *, timeout: float = 6.0) -> CBMSnapshot:
    """Poll a CBM over SSH using read-only ICC query commands."""
    try:
        import paramiko
    except ImportError as exc:
        raise CBMError("paramiko is not installed; rebuild/install requirements first") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            host,
            port=22,
            username=username,
            password=password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        channel = client.invoke_shell(width=160, height=40)
        _read_available(channel, 1.0)
        channel.send("i\n")
        _read_available(channel, 0.5)

        outputs: dict[str, str] = {}
        for command in ("tx_cfg ?", "rx_cfg ?", "all_stat ?"):
            channel.send(command + "\n")
            outputs[command] = _read_available(channel, 1.0)

        return CBMSnapshot(
            tx_config=parse_icc_response(outputs["tx_cfg ?"], "TX_CFG"),
            rx_config=parse_icc_response(outputs["rx_cfg ?"], "RX_CFG"),
            status=parse_icc_response(outputs["all_stat ?"], "ALL_STAT"),
        )
    except Exception as exc:
        raise CBMError(str(exc)) from exc
    finally:
        client.close()


def cbm_diagnostic(host: str, username: str, password: str, *, timeout: float = 6.0) -> str:
    """Return the raw ICC output for the status/config commands (read-only diagnostics).

    Lets an operator/administrator see exactly what the modem reports and how the parser
    interprets it, without guessing field names.
    """
    try:
        import paramiko
    except ImportError as exc:
        raise CBMError("paramiko is not installed; rebuild/install requirements first") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    commands = ("tx_cfg ?", "rx_cfg ?", "all_stat ?")
    parsers = {"tx_cfg ?": "TX_CFG", "rx_cfg ?": "RX_CFG", "all_stat ?": "ALL_STAT"}
    sections: list[str] = []
    try:
        client.connect(
            host, port=22, username=username, password=password,
            timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
            look_for_keys=False, allow_agent=False,
        )
        channel = client.invoke_shell(width=200, height=40)
        _read_available(channel, 1.0)
        channel.send("i\n")
        _read_available(channel, 0.5)
        for command in commands:
            channel.send(command + "\n")
            raw = _read_available(channel, 1.5)
            parsed = parse_icc_response(raw, parsers[command])
            sections.append(
                f"### {command}\n--- raw ---\n{raw.strip()}\n"
                f"--- parsed ({len(parsed)} fields) ---\n"
                + "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
            )
        return "\n\n".join(sections)
    except Exception as exc:
        raise CBMError(str(exc)) from exc
    finally:
        client.close()

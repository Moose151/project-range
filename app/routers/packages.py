import json
import io
import zipfile
from urllib.parse import quote_plus
from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, is_testing_state
from app.models import (
    User, Signal, SignalPackage, SignalPackageEntry,
    ModulationType, FecType, SignalSource, AntennaType, AuditLog, RFDevice, SerialPackage,
)
from app.config import MAX_UPLOAD_BYTES
from app.upload_validation import (
    validate_total_upload_size,
    validate_upload_file,
    validate_zip_member_count,
)
from app.ops_health import package_health_badges

router = APIRouter(prefix="/packages")
from app.templating import templates

BANDS = ["C", "X", "Ku", "Ka", "Other"]
FREQ_UNITS = ["MHz", "GHz"]
POWER_UNITS = ["dBm", "dBW", "W"]
CBM_PATHS = [
    ("", "None"),
    ("tx", "Tx"),
    ("rx", "Rx"),
    ("tx_rx", "Tx/Rx"),
    ("dvb", "DVB"),
]
PACKAGE_UPLOAD_EXTENSIONS = {"txt", "cfg", "conf", "json", "zip"}
CBM_TEXT_EXTENSIONS = {"txt", "cfg", "conf"}

CBM_WMASK_DEFAULT = (
    "BPSK:1/2TURBO+BPSK:2/3TURBO+BPSK:3/4TURBO+BPSK:7/8TURBO+BPSK:19/20TURBO+"
    "QPSK:1/2TURBO+QPSK:2/3TURBO+QPSK:3/4TURBO+QPSK:7/8TURBO+QPSK:19/20TURBO+"
    "8-PSK:1/2TURBO+8-PSK:2/3TURBO+8-PSK:3/4TURBO+8-PSK:7/8TURBO+8-PSK:19/20TURBO+"
    "16-APSK:1/2TURBO+16-APSK:2/3TURBO+16-APSK:3/4TURBO+16-APSK:7/8TURBO+16-APSK:19/20TURBO"
)

CBM_DEFAULTS = {
    "TX_OP": "OFF",
    "TXIF_LVL": "-30.0",
    "TX_MOP": "EBEM",
    "TX_SMOP": "TURBO",
    "TX_DR": "0",
    "TX_SCR": "OFF",
    "TX_EMBCH": "ON",
    "ITA_ENGAGE": "AUTO",
    "ITT_OP": "disable",
    "ITT_WMASK": CBM_WMASK_DEFAULT,
    "ITR_OP": "disable",
    "ITR_WMASK": CBM_WMASK_DEFAULT,
    "ITR_MRGN": "0.25",
    "ITR_HYST": "0.5",
    "AUPC_OP": "disable",
    "AUPC_PWR_RNG": "default",
    "AUPC_DESNO_RNG": "default",
    "TXPI_OP": "disable",
    "TXPI_INH_DLY": "0",
    "TXPI_REAC_STEP": "1.0",
    "TXPI_REAC_MODE": "auto",
    "TXPI_REAC_DLY": "0",
    "AUPC_TGT_DESNO_CFG": "default",
    "AUPC_MAX_PWR_CFG": "default",
    "RX_OP": "OFF",
    "RX_MOP": "EBEM",
    "RX_SMOP": "TURBO",
    "RX_DR": "0",
    "RX_SCR": "OFF",
    "RX_EMBCH": "ON",
    "EQUAL_OP": "OFF",
    "CFG_NAME": "ProjectRange",
    "CFG_VER": "9",
    "FRQ_REF": "INTERNAL",
    "LBK_CFG": "NONE",
    "MDM_ADDR": "0",
    "TX_LNKID": "PUBLIC",
    "RX_LNKID": "PUBLIC",
    "IP_ADDR": "192.168.1.1",
    "SUB_MSK": "255.255.255.0",
    "IP_GWY": "0.0.0.0",
    "BB_INTF": "EIA-422/530",
    "SNMP_COMM": "PUBLIC",
    "TRAP_ADDR": "192.168.1.1",
    "DEM_OP": "Off",
    "BERT_TXPAT": "ALL_MARK",
    "BERT_RXPAT": "ALL_MARK",
    "BERT_SLD": "1",
    "BERT_SLOP": "MEDIUM",
    "EBNO_LVL": "OFF",
    "EBNOTRAP_CFG": "1/4SEC",
    "EBNOTRAP_THRESH": "DEFAULT",
    "BBI_CFG": "NORMAL",
    "BBO_CFG": "NORMAL",
    "ALM_MUTE": "On",
    "TRANSEC_MODE": "SMAT-BASED",
    "KE_SERIAL_ID": "NULL",
    "ESEM_AUTO_NEG": "ON",
    "ESEM_PORT_MODE": "FULL-DUPLEX",
    "ESEM_PORT_SPEED": "100",
    "ESEM_SIMPLEX_SUP": "ON",
    "ESEM_PAUSE_FRAMES": "OFF",
    "ESEM_WINDOW_SIZE": "5",
    "ESEM_RF_PROP_DELAY": "250",
    "ESEM_CREDIT_PPPOE": "OFF",
    "PPPOE_KEEP_ALIVE": "1",
    "PPPOE_INIT_RETRY": "OFF",
    "ESEM_THRESH_TXDR": "64000",
    "ESEM_THRESH_RXDR": "64000",
    "ETH_TX_DR": "64000",
    "ETH_RX_DR": "64000",
    "FAT_OP": "NOP",
}

CBM_EXPORT_ORDER = [
    "TX_OP", "TXIF_LVL", "TXIF_FRQ", "TX_MOP", "TX_SMOP", "TX_MOD", "TX_DR", "TX_SR", "TX_CODE",
    "TX_SCR", "TX_EMBCH", "ITA_ENGAGE", "ITT_OP", "ITT_WMASK", "ITR_OP", "ITR_WMASK",
    "ITR_MRGN", "ITR_HYST", "AUPC_OP", "AUPC_PWR_RNG", "AUPC_DESNO_RNG", "TXPI_OP",
    "TXPI_INH_DLY", "TXPI_REAC_STEP", "TXPI_REAC_MODE", "TXPI_REAC_DLY", "AUPC_TGT_DESNO_CFG",
    "AUPC_MAX_PWR_CFG", "RX_OP", "RXIF_FRQ", "RX_MOP", "RX_SMOP", "RX_MOD",
    "RX_DR", "RX_SR", "RX_CODE", "RX_SCR", "RX_EMBCH", "EQUAL_OP", "CFG_NAME", "CFG_VER",
    "FRQ_REF", "LBK_CFG", "MDM_ADDR", "TX_LNKID", "RX_LNKID", "IP_ADDR", "SUB_MSK", "IP_GWY",
    "BB_INTF", "SNMP_COMM", "TRAP_ADDR", "DEM_OP", "BERT_TXPAT",
    "BERT_RXPAT", "BERT_SLD", "BERT_SLOP", "EBNO_LVL", "BBI_CFG", "BBO_CFG", "ALM_MUTE",
    "EBNOTRAP_CFG", "EBNOTRAP_THRESH", "TRANSEC_MODE", "KE_SERIAL_ID", "ESEM_AUTO_NEG", "ESEM_PORT_MODE", "ESEM_PORT_SPEED",
    "ESEM_SIMPLEX_SUP", "ESEM_PAUSE_FRAMES", "ESEM_WINDOW_SIZE", "ESEM_RF_PROP_DELAY",
    "ESEM_CREDIT_PPPOE", "PPPOE_KEEP_ALIVE", "PPPOE_INIT_RETRY", "ESEM_THRESH_TXDR",
    "ESEM_THRESH_RXDR", "ETH_TX_DR", "ETH_RX_DR", "FAT_OP",
]


def _dropdown_lists(db: Session) -> dict:
    testing = is_testing_state(db)
    mod_types = [m.name for m in db.query(ModulationType).filter(ModulationType.is_active == True).order_by(ModulationType.display_order).all()]
    fec_types = [f.name for f in db.query(FecType).filter(FecType.is_active == True).order_by(FecType.display_order).all()]
    antennas = [a.name for a in db.query(AntennaType).filter(AntennaType.is_active == True).order_by(AntennaType.display_order).all()]
    signals = [s.name for s in db.query(Signal).filter(Signal.is_active == True).order_by(Signal.name).all()]
    cbm_devices = (
        db.query(RFDevice)
        .filter(
            RFDevice.is_active == True,
            RFDevice.device_type == "modem",
            RFDevice.cbm_sync_enabled == True,
            RFDevice.is_testing == testing,
        )
        .order_by(RFDevice.name)
        .all()
    )
    modem_devices = (
        db.query(RFDevice)
        .filter(
            RFDevice.is_active == True,
            RFDevice.device_type == "modem",
            RFDevice.is_testing == testing,
        )
        .order_by(RFDevice.name)
        .all()
    )
    source_names = [s.name for s in db.query(SignalSource).filter(SignalSource.is_active == True).order_by(SignalSource.display_order).all()]
    for device in modem_devices:
        if device.name not in source_names:
            source_names.append(device.name)
    return {
        "mod_types": mod_types or ["BPSK", "QPSK", "8PSK", "16APSK", "32APSK"],
        "fec_types": fec_types or ["1/2", "2/3", "3/4", "5/6", "7/8", "8/9", "9/10"],
        "signal_sources": source_names,
        "antenna_types": antennas,
        "registry_signals": signals,
        "cbm_devices": cbm_devices,
        "cbm_paths": CBM_PATHS,
        "bands": BANDS,
        "freq_units": FREQ_UNITS,
        "power_units": POWER_UNITS,
    }


def _package_to_dict(pkg: SignalPackage) -> dict:
    """Serialise a package to a dict for JSON export."""
    return {
        "name": pkg.name,
        "description": pkg.description or "",
        "rf_config": {
            "band": pkg.band or "",
            "antenna": pkg.antenna or "",
            "tx_lo": pkg.tx_lo,
            "rx_lo": pkg.rx_lo,
            "ttf": pkg.ttf,
            "ttf_direction": pkg.ttf_direction or "+",
            "freq_unit": pkg.freq_unit or "MHz",
        },
        "signals": [
            {
                "name": e.signal_name,
                "description": e.description or "",
                "band": e.band or "",
                "tx_if": e.tx_if,
                "tx_rf": e.tx_rf,
                "rx_rf": e.rx_rf,
                "rx_if": e.rx_if,
                "freq_unit": e.freq_unit,
                "modulation": e.modulation or "",
                "fec": e.fec or "",
                "inner_code": e.inner_code or "",
                "symbol_rate": e.symbol_rate or "",
                "power": e.power,
                "power_unit": e.power_unit,
                "source": e.source or "",
                "antenna": e.antenna or "",
                "cbm_device": e.cbm_device.name if e.cbm_device else "",
                "cbm_path": e.cbm_path or "",
                "notes": e.notes or "",
            }
            for e in pkg.signals
        ],
    }


def _dict_to_entries(data: dict) -> list[dict]:
    """Parse a JSON package dict and return a list of entry field dicts."""
    entries = []
    for i, s in enumerate(data.get("signals", [])):
        fec, inner_code = _split_cbm_code(
            str(s.get("fec", "")).strip(),
            str(s.get("inner_code", "")).strip(),
        )
        entries.append({
            "signal_name": str(s.get("name", "")).strip(),
            "description": str(s.get("description", "")).strip() or None,
            "band": str(s.get("band", "")).strip() or None,
            "tx_if": _float_or_none(s.get("tx_if")),
            "tx_rf": _float_or_none(s.get("tx_rf")),
            "rx_rf": _float_or_none(s.get("rx_rf")),
            "rx_if": _float_or_none(s.get("rx_if")),
            "freq_unit": str(s.get("freq_unit", "MHz")).strip() or "MHz",
            "modulation": str(s.get("modulation", "")).strip() or None,
            "fec": fec,
            "inner_code": inner_code,
            "symbol_rate": str(s.get("symbol_rate", "")).strip() or None,
            "power": _float_or_none(s.get("power")),
            "power_unit": str(s.get("power_unit", "dBm")).strip() or "dBm",
            "source": str(s.get("source", "")).strip() or None,
            "antenna": str(s.get("antenna", "")).strip() or None,
            "cbm_path": str(s.get("cbm_path", "")).strip() or None,
            "notes": str(s.get("notes", "")).strip() or None,
            "display_order": i,
        })
    return entries


def _validated_json_package(content: bytes) -> dict:
    data = json.loads(content.decode("utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("signals"), list):
        raise ValueError("JSON file must be a Project Range package object with a 'signals' list.")
    if len(data["signals"]) > 500:
        raise ValueError("JSON package contains too many signals. Maximum is 500.")
    for i, signal in enumerate(data["signals"], start=1):
        if not isinstance(signal, dict):
            raise ValueError(f"JSON signal #{i} must be an object.")
    return data


def _safe_filename(value: str, fallback: str = "signal") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value.strip())
    return (cleaned.strip("._") or fallback)[:80]


def _cbm_pairs_from_text(text: str) -> dict[str, str]:
    text = text.strip().lstrip("\ufeff")
    if not text:
        raise ValueError("CBM config file is empty.")
    if text.startswith("STR_CFG"):
        first_comma = text.find(",")
        text = text[first_comma + 1:] if first_comma >= 0 else ""
    pairs: dict[str, str] = {}
    for part in text.replace("\r", "").replace("\n", "").split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().upper()
        if key:
            pairs[key] = value.strip()
    if "TXIF_FRQ" not in pairs and "RXIF_FRQ" not in pairs:
        raise ValueError("CBM config does not contain TXIF_FRQ or RXIF_FRQ.")
    return pairs


def _cbm_if_to_mhz(value: str | None) -> Optional[float]:
    raw = _float_or_none(value)
    if raw is None:
        return None
    # CBM export uses kHz-style integers, e.g. 1205000 = 1205.000 MHz.
    return raw / 1000.0


def _mhz_to_cbm_if(value: float | None) -> str:
    if value is None:
        return "0"
    cbm_value = value * 1000.0
    return str(int(round(cbm_value))) if abs(cbm_value - round(cbm_value)) < 0.001 else f"{cbm_value:.3f}".rstrip("0").rstrip(".")


def _cbm_symbol_to_project(value: str | None) -> str | None:
    raw = _float_or_none(value)
    if raw is None:
        return None
    scaled = raw / 1000.0
    return f"{scaled:.6f}".rstrip("0").rstrip(".")


def _project_symbol_to_cbm(value: str | None) -> str:
    raw = _float_or_none(value)
    if raw is None:
        return "0"
    scaled = raw * 1000.0
    return str(int(round(scaled))) if abs(scaled - round(scaled)) < 0.001 else f"{scaled:.3f}".rstrip("0").rstrip(".")


def _cbm_mod_to_project(value: str | None) -> str | None:
    if not value:
        return None
    mapping = {"8-PSK": "8PSK", "16-APSK": "16APSK", "32-APSK": "32APSK"}
    return mapping.get(value.strip().upper(), value.strip())


def _project_mod_to_cbm(value: str | None) -> str:
    if not value:
        return "BPSK"
    mapping = {"8PSK": "8-PSK", "16APSK": "16-APSK", "32APSK": "32-APSK"}
    return mapping.get(value.strip().upper(), value.strip())


def _split_cbm_code(code: str | None, smop: str | None = None) -> tuple[str | None, str | None]:
    raw = (code or "").strip()
    inner = (smop or "").strip() or None
    if not raw:
        return None, inner
    base = raw.split(":", 1)[0].strip()
    if inner and base.upper().endswith(inner.upper()):
        fec = base[: -len(inner)].strip()
        return fec or None, inner
    for marker in ("TURBO", "LDPC", "VITERBI", "RS", "TPC"):
        idx = base.upper().find(marker)
        if idx > 0:
            return base[:idx].strip() or None, inner or base[idx:].strip()
    return base or None, inner


def _cbm_code_from_fields(fec: str | None, inner_code: str | None) -> str:
    rate = (fec or "").strip()
    inner = (inner_code or "").strip()
    if not rate:
        return ""
    if not inner:
        return rate
    suffix = inner if ":" in inner else f"{inner}:1024"
    return f"{rate}{suffix}"


def _source_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _cbm_source_device(db: Session, source: str, testing: bool) -> RFDevice | None:
    name = source.strip()
    if not name:
        return None
    devices = (
        db.query(RFDevice)
        .filter(
            RFDevice.is_active == True,
            RFDevice.device_type == "modem",
            RFDevice.cbm_sync_enabled == True,
            RFDevice.is_testing == testing,
        )
        .order_by(RFDevice.name)
        .all()
    )
    key = _source_key(name)
    for device in devices:
        if device.name == name or _source_key(device.name) == key:
            return device
    return None


def _cbm_source_device_id(db: Session, source: str, testing: bool) -> int | None:
    device = _cbm_source_device(db, source, testing)
    return device.id if device else None


def _clear_modem_from_other_entries(db: Session, cbm_device_id: int, except_entry_id: int | None = None) -> None:
    """Enforce one-to-one modem assignment: clear this modem from any other package signal entries."""
    if not cbm_device_id:
        return
    q = db.query(SignalPackageEntry).filter(
        SignalPackageEntry.cbm_device_id == cbm_device_id
    )
    if except_entry_id is not None:
        q = q.filter(SignalPackageEntry.id != except_entry_id)
    for entry in q.all():
        entry.cbm_device_id = None
        entry.source = None


def _cbm_entry_from_text(text: str, filename: str, display_order: int = 0) -> dict:
    pairs = _cbm_pairs_from_text(text)
    stem = (filename.rsplit("/", 1)[-1] or "").rsplit(".", 1)[0]
    signal_name = stem or pairs.get("CFG_NAME", "Imported Signal")
    tx_if = _cbm_if_to_mhz(pairs.get("TXIF_FRQ"))
    rx_if = _cbm_if_to_mhz(pairs.get("RXIF_FRQ"))
    modulation = _cbm_mod_to_project(pairs.get("TX_MOD") or pairs.get("RX_MOD"))
    symbol_rate = _cbm_symbol_to_project(pairs.get("TX_SR") or pairs.get("RX_SR"))
    inner_code = pairs.get("TX_SMOP") or pairs.get("RX_SMOP")
    fec, inner_code = _split_cbm_code(pairs.get("TX_CODE") or pairs.get("RX_CODE"), inner_code)
    power = _float_or_none(pairs.get("TXIF_LVL"))
    notes = "Imported from CBM-400 config"
    if pairs.get("TX_OP") or pairs.get("RX_OP") or pairs.get("ITA_ENGAGE"):
        notes += f" (TX_OP={pairs.get('TX_OP', 'n/a')}, RX_OP={pairs.get('RX_OP', 'n/a')}, ITA_ENGAGE={pairs.get('ITA_ENGAGE', 'n/a')})"
    return {
        "signal_name": signal_name.strip(),
        "description": f"CBM-400 config import: {filename}"[:256],
        "band": None,
        "tx_if": tx_if,
        "tx_rf": None,
        "rx_rf": None,
        "rx_if": rx_if,
        "freq_unit": "MHz",
        "modulation": modulation,
        "fec": fec,
        "inner_code": inner_code,
        "symbol_rate": symbol_rate,
        "power": power,
        "power_unit": "dBm",
        "eb_no": None,
        "source": pairs.get("CFG_NAME") or None,
        "antenna": None,
        "cbm_path": "tx_rx" if tx_if is not None and rx_if is not None else ("tx" if tx_if is not None else "rx"),
        "notes": notes,
        "display_order": display_order,
    }


def _freq_to_mhz(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    return value * 1000.0 if (unit or "MHz") == "GHz" else value


def _round_freq(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def _package_rf_values(pkg: SignalPackage | None = None, form: dict | None = None) -> dict:
    if pkg is not None:
        return {
            "tx_lo": pkg.tx_lo,
            "rx_lo": pkg.rx_lo,
            "ttf": pkg.ttf,
            "ttf_direction": pkg.ttf_direction or "+",
            "freq_unit": pkg.freq_unit or "MHz",
        }
    form = form or {}
    return {
        "tx_lo": _float_or_none(form.get("tx_lo")),
        "rx_lo": _float_or_none(form.get("rx_lo")),
        "ttf": _float_or_none(form.get("ttf")),
        "ttf_direction": str(form.get("ttf_direction") or "+"),
        "freq_unit": str(form.get("freq_unit") or "MHz"),
    }


def _apply_package_rf_to_entry(fields: dict, rf: dict) -> dict:
    """Fill missing imported RF values from package LO/TTF settings.

    CBM text exports normally provide IF values only. Store imported signal
    frequencies in MHz so they remain directly comparable to modem reads.
    """
    unit = rf.get("freq_unit") or "MHz"
    tx_lo = _freq_to_mhz(rf.get("tx_lo"), unit)
    rx_lo = _freq_to_mhz(rf.get("rx_lo"), unit)
    ttf = _freq_to_mhz(rf.get("ttf"), unit)
    sign = -1 if rf.get("ttf_direction") == "-" else 1

    tx_if = _freq_to_mhz(fields.get("tx_if"), fields.get("freq_unit") or "MHz")
    tx_rf = _freq_to_mhz(fields.get("tx_rf"), fields.get("freq_unit") or "MHz")
    rx_rf = _freq_to_mhz(fields.get("rx_rf"), fields.get("freq_unit") or "MHz")
    rx_if = _freq_to_mhz(fields.get("rx_if"), fields.get("freq_unit") or "MHz")

    if tx_rf is None and tx_if is not None and tx_lo is not None:
        tx_rf = tx_if + tx_lo
    if rx_rf is None and rx_if is not None and rx_lo is not None:
        rx_rf = rx_if + rx_lo
    if rx_rf is None and tx_rf is not None and ttf is not None:
        rx_rf = tx_rf + sign * ttf
    if tx_rf is None and rx_rf is not None and ttf is not None:
        tx_rf = rx_rf - sign * ttf
    if tx_if is None and tx_rf is not None and tx_lo is not None:
        tx_if = tx_rf - tx_lo
    if rx_if is None and rx_rf is not None and rx_lo is not None:
        rx_if = rx_rf - rx_lo

    fields.update({
        "tx_if": _round_freq(tx_if),
        "tx_rf": _round_freq(tx_rf),
        "rx_rf": _round_freq(rx_rf),
        "rx_if": _round_freq(rx_if),
        "freq_unit": "MHz",
    })
    return fields


async def _uploaded_signal_files(request: Request) -> list[tuple[str, bytes]]:
    form = await request.form()
    uploads = [item for _, item in form.multi_items() if hasattr(item, "filename") and item.filename]
    if not uploads:
        raise ValueError("Select at least one CBM .txt, .zip, or legacy Project Range .json file.")

    files: list[tuple[str, bytes]] = []
    total_bytes = 0
    for upload in uploads:
        content = await upload.read()
        total_bytes += len(content)
        validate_total_upload_size(total_bytes)
        filename = validate_upload_file(
            upload.filename,
            content,
            allowed_extensions=PACKAGE_UPLOAD_EXTENSIONS,
        )
        if zipfile.is_zipfile(io.BytesIO(content)):
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                infos = [info for info in zf.infolist() if not info.is_dir()]
                validate_zip_member_count(len(infos))
                for info in infos:
                    name = info.filename
                    basename = name.rsplit("/", 1)[-1]
                    if basename.startswith("."):
                        continue
                    if not name.lower().endswith((".txt", ".cfg", ".conf")):
                        continue
                    validate_upload_file(basename, b"", allowed_extensions=CBM_TEXT_EXTENSIONS)
                    if info.file_size > MAX_UPLOAD_BYTES:
                        raise ValueError(f"{basename} is too large. Maximum size is {MAX_UPLOAD_BYTES // 1024} KB.")
                    total_bytes += info.file_size
                    validate_total_upload_size(total_bytes)
                    files.append((basename, zf.read(info)))
        else:
            files.append((filename, content))
    return files


def _entries_from_uploaded_files(files: list[tuple[str, bytes]], display_offset: int = 0) -> list[dict]:
    entries = []
    for i, (filename, content) in enumerate(files):
        if filename.lower().endswith(".json"):
            data = _validated_json_package(content)
            for fields in _dict_to_entries(data):
                fields["display_order"] = display_offset + len(entries)
                entries.append(fields)
            continue
        text = content.decode("utf-8-sig", errors="replace")
        entries.append(_cbm_entry_from_text(text, filename, display_order=display_offset + len(entries)))
    if not entries:
        raise ValueError("No CBM config text files were found to import.")
    return entries


def _add_imported_entries_to_package(
    pkg: SignalPackage,
    entries: list[dict],
    db: Session,
    testing: bool,
    rf: dict | None = None,
) -> int:
    count = 0
    rf = rf or _package_rf_values(pkg=pkg)
    for fields in entries:
        if not fields["signal_name"]:
            continue
        _apply_package_rf_to_entry(fields, rf)
        device = _cbm_source_device(db, fields.get("source") or "", testing)
        if device:
            fields["source"] = device.name
            fields["cbm_device_id"] = device.id
        db.add(SignalPackageEntry(package_id=pkg.id, **fields))
        count += 1
    return count


def _cbm_text_from_entry(entry: SignalPackageEntry) -> str:
    values = dict(CBM_DEFAULTS)
    values.update({
        "TXIF_FRQ": _mhz_to_cbm_if(entry.tx_if),
        "RXIF_FRQ": _mhz_to_cbm_if(entry.rx_if if entry.rx_if is not None else entry.tx_if),
        "TX_SMOP": str(entry.inner_code or CBM_DEFAULTS["TX_SMOP"]),
        "RX_SMOP": str(entry.inner_code or CBM_DEFAULTS["RX_SMOP"]),
        "TX_MOD": _project_mod_to_cbm(entry.modulation),
        "RX_MOD": _project_mod_to_cbm(entry.modulation),
        "TX_SR": _project_symbol_to_cbm(entry.symbol_rate),
        "RX_SR": _project_symbol_to_cbm(entry.symbol_rate),
        "TX_CODE": _cbm_code_from_fields(entry.fec, entry.inner_code),
        "RX_CODE": _cbm_code_from_fields(entry.fec, entry.inner_code),
        "TXIF_LVL": str(entry.power if entry.power is not None else -30.0),
        "CFG_NAME": _safe_filename(entry.source or entry.signal_name, "ProjectRange"),
    })
    parts = [f"{key}={values[key]}" for key in CBM_EXPORT_ORDER if values.get(key) is not None]
    return "STR_CFG 2," + ",".join(parts) + "\r\n"


def _float_or_none(v) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (ValueError, TypeError):
        return None


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def packages_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    packages = db.query(SignalPackage).filter(SignalPackage.is_testing == testing).order_by(SignalPackage.created_at.desc()).all()
    return templates.TemplateResponse(request, "packages.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "packages": packages,
        "package_health": {pkg.id: package_health_badges(pkg) for pkg in packages},
        "toast": request.query_params.get("toast", ""),
        "error": request.query_params.get("error", ""),
        "page": "packages",
    })


# ── Create ────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def package_new_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    return templates.TemplateResponse(request, "package_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "package": None,
        "packages_for_duplicate": db.query(SignalPackage).filter(SignalPackage.is_testing == testing).order_by(SignalPackage.name).all(),
        "page": "packages",
        **_dropdown_lists(db),
    })


@router.post("/new")
async def package_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    loop_mode: str = Form("live"),
    band: str = Form(""),
    antenna: str = Form(""),
    tx_lo: Optional[float] = Form(None),
    rx_lo: Optional[float] = Form(None),
    ttf: Optional[float] = Form(None),
    ttf_direction: str = Form("+"),
    freq_unit: str = Form("MHz"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    closed = loop_mode == "closed"
    pkg = SignalPackage(
        name=name.strip(),
        description=description.strip() or None,
        loop_mode="closed" if closed else "live",
        # Closed-loop (IF-only) packages carry no RF config.
        band=None if closed else (band or None),
        antenna=None if closed else (antenna.strip() or None),
        tx_lo=None if closed else tx_lo,
        rx_lo=None if closed else rx_lo,
        ttf=None if closed else ttf,
        ttf_direction=ttf_direction or "+",
        freq_unit=freq_unit or "MHz",
        is_testing=is_testing_state(db),
        created_by_id=current_user.id,
    )
    db.add(pkg)
    db.flush()
    db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_CREATE",
                    entity_type="SignalPackage", entity_id=pkg.id, new_value=pkg.name))
    db.commit()
    return RedirectResponse(f"/packages/{pkg.id}?toast=Package+created", status_code=302)


# ── Edit (add/update/remove signals) ─────────────────────────────────────────

@router.get("/{pkg_id:int}", response_class=HTMLResponse)
async def package_detail(
    pkg_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id,
        SignalPackage.is_testing == is_testing_state(db),
    ).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    return templates.TemplateResponse(request, "package_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "package": pkg,
        "packages_for_duplicate": [],
        "toast": request.query_params.get("toast", ""),
        "error": request.query_params.get("error", ""),
        "page": "packages",
        **_dropdown_lists(db),
    })


@router.post("/{pkg_id:int}/update")
async def package_update_meta(
    pkg_id: int,
    name: str = Form(...),
    description: str = Form(""),
    loop_mode: str = Form("live"),
    band: str = Form(""),
    antenna: str = Form(""),
    tx_lo: Optional[float] = Form(None),
    rx_lo: Optional[float] = Form(None),
    ttf: Optional[float] = Form(None),
    ttf_direction: str = Form("+"),
    freq_unit: str = Form("MHz"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    if pkg:
        closed = loop_mode == "closed"
        pkg.name = name.strip() or pkg.name
        pkg.description = description.strip() or None
        pkg.loop_mode = "closed" if closed else "live"
        # Closed-loop (IF-only) packages carry no RF config — clear it if switched.
        pkg.band = None if closed else (band or None)
        pkg.antenna = None if closed else (antenna.strip() or None)
        pkg.tx_lo = None if closed else tx_lo
        pkg.rx_lo = None if closed else rx_lo
        pkg.ttf = None if closed else ttf
        pkg.ttf_direction = ttf_direction or "+"
        pkg.freq_unit = freq_unit or "MHz"
        if closed:
            # Drop RF-only fields from every signal in the package.
            for e in pkg.signals:
                e.tx_rf = None
                e.rx_rf = None
                e.band = None
                e.antenna = None
        pkg.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Package+updated", status_code=302)


@router.post("/{pkg_id:int}/signals/add")
async def package_signal_add(
    pkg_id: int,
    signal_name: str = Form(...),
    description: str = Form(""),
    band: str = Form(""),
    tx_if: Optional[float] = Form(None),
    tx_rf: Optional[float] = Form(None),
    rx_rf: Optional[float] = Form(None),
    rx_if: Optional[float] = Form(None),
    freq_unit: str = Form("MHz"),
    modulation: str = Form(""),
    fec: str = Form(""),
    inner_code: str = Form(""),
    symbol_rate: str = Form(""),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    source: str = Form(""),
    antenna: str = Form(""),
    cbm_path: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not symbol_rate.strip():
        return RedirectResponse(f"/packages/{pkg_id}?error=Symbol+rate+is+required", status_code=302)
    testing = is_testing_state(db)
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == testing).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    source_name = source.strip()
    cbm_device = _cbm_source_device(db, source_name, testing)
    cbm_device_id = cbm_device.id if cbm_device else None
    if cbm_device:
        source_name = cbm_device.name
    if cbm_device_id:
        _clear_modem_from_other_entries(db, cbm_device_id)
    order = len(pkg.signals)
    entry = SignalPackageEntry(
        package_id=pkg_id,
        display_order=order,
        signal_name=signal_name.strip(),
        description=description.strip() or None,
        band=band or None,
        tx_if=tx_if, tx_rf=tx_rf, rx_rf=rx_rf, rx_if=rx_if,
        freq_unit=freq_unit or "MHz",
        modulation=modulation or None,
        fec=fec or None,
        inner_code=inner_code.strip() or None,
        symbol_rate=symbol_rate or None,
        power=power, power_unit=power_unit or "dBm",
        eb_no=None,
        source=source_name or None,
        antenna=antenna.strip() or None,
        cbm_device_id=cbm_device_id,
        cbm_path=cbm_path or None,
        notes=notes.strip() or None,
    )
    pkg.updated_at = datetime.utcnow()
    db.add(entry)
    db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Signal+added", status_code=302)


@router.post("/{pkg_id:int}/signals/{entry_id:int}/update")
async def package_signal_update(
    pkg_id: int,
    entry_id: int,
    signal_name: str = Form(...),
    description: str = Form(""),
    band: str = Form(""),
    tx_if: Optional[float] = Form(None),
    tx_rf: Optional[float] = Form(None),
    rx_rf: Optional[float] = Form(None),
    rx_if: Optional[float] = Form(None),
    freq_unit: str = Form("MHz"),
    modulation: str = Form(""),
    fec: str = Form(""),
    inner_code: str = Form(""),
    symbol_rate: str = Form(""),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    source: str = Form(""),
    antenna: str = Form(""),
    cbm_path: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not symbol_rate.strip():
        return RedirectResponse(f"/packages/{pkg_id}?error=Symbol+rate+is+required", status_code=302)
    testing = is_testing_state(db)
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == testing).first()
    source_name = source.strip()
    cbm_device = _cbm_source_device(db, source_name, testing)
    cbm_device_id = cbm_device.id if cbm_device else None
    if cbm_device:
        source_name = cbm_device.name
    if cbm_device_id:
        _clear_modem_from_other_entries(db, cbm_device_id, except_entry_id=entry_id)
    entry = db.query(SignalPackageEntry).filter(
        SignalPackageEntry.id == entry_id,
        SignalPackageEntry.package_id == pkg_id,
    ).first() if pkg else None
    if entry:
        entry.signal_name = signal_name.strip()
        entry.description = description.strip() or None
        entry.band = band or None
        entry.tx_if = tx_if; entry.tx_rf = tx_rf
        entry.rx_rf = rx_rf; entry.rx_if = rx_if
        entry.freq_unit = freq_unit or "MHz"
        entry.modulation = modulation or None
        entry.fec = fec or None
        entry.inner_code = inner_code.strip() or None
        entry.symbol_rate = symbol_rate or None
        entry.power = power; entry.power_unit = power_unit or "dBm"
        entry.eb_no = None
        entry.source = source_name or None
        entry.antenna = antenna.strip() or None
        entry.cbm_device_id = cbm_device_id
        entry.cbm_path = cbm_path or None
        entry.notes = notes.strip() or None
        pkg.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Signal+updated", status_code=302)


@router.post("/{pkg_id:int}/signals/{entry_id:int}/delete")
async def package_signal_delete(
    pkg_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    entry = db.query(SignalPackageEntry).filter(
        SignalPackageEntry.id == entry_id,
        SignalPackageEntry.package_id == pkg_id,
    ).first() if pkg else None
    if entry:
        db.delete(entry)
        pkg.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Signal+removed", status_code=302)


@router.post("/{pkg_id:int}/duplicate")
async def package_duplicate(
    pkg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    orig = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == testing).first()
    if not orig:
        return RedirectResponse("/packages", status_code=302)
    copy = SignalPackage(
        name=f"{orig.name} (copy)",
        description=orig.description,
        band=orig.band,
        antenna=orig.antenna,
        tx_lo=orig.tx_lo,
        rx_lo=orig.rx_lo,
        ttf=orig.ttf,
        ttf_direction=orig.ttf_direction,
        freq_unit=orig.freq_unit,
        is_testing=testing,
        created_by_id=current_user.id,
    )
    db.add(copy)
    db.flush()
    for entry in orig.signals:
        db.add(SignalPackageEntry(
            package_id=copy.id,
            display_order=entry.display_order,
            signal_name=entry.signal_name,
            description=entry.description,
            band=entry.band,
            tx_if=entry.tx_if, tx_rf=entry.tx_rf,
            rx_rf=entry.rx_rf, rx_if=entry.rx_if,
            freq_unit=entry.freq_unit,
            modulation=entry.modulation,
            fec=entry.fec,
            inner_code=entry.inner_code,
            symbol_rate=entry.symbol_rate,
            power=entry.power, power_unit=entry.power_unit,
            eb_no=None,
            source=entry.source,
            antenna=entry.antenna,
            cbm_device_id=entry.cbm_device_id,
            cbm_path=entry.cbm_path,
            notes=entry.notes,
        ))
    db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_DUPLICATE",
                    entity_type="SignalPackage", entity_id=copy.id,
                    new_value=f"Copy of {orig.name}"))
    db.commit()
    return RedirectResponse(f"/packages/{copy.id}?toast=Package+duplicated", status_code=302)


def _copy_package_to_workspace(
    db: Session, pkg: "SignalPackage", target_testing: bool, actor_id: int
) -> "SignalPackage":
    """Copy a package and all its signals into the target workspace (is_testing).

    cbm_device_id is cleared on the copy — CBM devices are workspace-specific and
    the operator should re-assign the Source in the target workspace.
    """
    copy = SignalPackage(
        name=pkg.name,
        description=pkg.description,
        band=pkg.band,
        antenna=pkg.antenna,
        tx_lo=pkg.tx_lo,
        rx_lo=pkg.rx_lo,
        ttf=pkg.ttf,
        ttf_direction=pkg.ttf_direction,
        freq_unit=pkg.freq_unit,
        loop_mode=pkg.loop_mode,
        is_testing=target_testing,
        created_by_id=actor_id,
    )
    copy._preserve_testing_scope = True
    db.add(copy)
    db.flush()
    for entry in pkg.signals:
        db.add(SignalPackageEntry(
            package_id=copy.id,
            display_order=entry.display_order,
            signal_name=entry.signal_name,
            description=entry.description,
            band=entry.band,
            tx_if=entry.tx_if, tx_rf=entry.tx_rf,
            rx_rf=entry.rx_rf, rx_if=entry.rx_if,
            freq_unit=entry.freq_unit,
            modulation=entry.modulation,
            fec=entry.fec,
            inner_code=entry.inner_code,
            symbol_rate=entry.symbol_rate,
            power=entry.power, power_unit=entry.power_unit,
            eb_no=None,
            source=entry.source,
            antenna=entry.antenna,
            cbm_device_id=None,   # device IDs are workspace-specific
            cbm_path=entry.cbm_path,
            notes=entry.notes,
        ))
    return copy


@router.post("/{pkg_id:int}/copy-to-other")
async def package_copy_to_other(
    pkg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copy a package into the other workspace (Live ↔ Sandbox)."""
    testing = is_testing_state(db)
    orig = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id, SignalPackage.is_testing == testing,
    ).first()
    if not orig:
        return RedirectResponse("/packages", status_code=302)
    target = not testing
    copy = _copy_package_to_workspace(db, orig, target, current_user.id)
    dest = "Sandbox" if target else "Live"
    db.add(AuditLog(
        user_id=current_user.id, action_type="PACKAGE_COPY_WORKSPACE",
        entity_type="SignalPackage", entity_id=copy.id,
        new_value=f"Copied '{orig.name}' from {'Sandbox' if testing else 'Live'} to {dest}",
    ))
    db.commit()
    msg = f'Package "{orig.name}" copied to {dest}'
    return RedirectResponse(f"/packages?toast={quote_plus(msg)}", status_code=302)


@router.post("/{pkg_id:int}/signals/reorder")
async def package_signals_reorder(
    pkg_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    form = await request.form()
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    for key, val in form.items():
        if key.startswith("order_"):
            entry_id = int(key.split("_")[1])
            entry = db.query(SignalPackageEntry).filter(
                SignalPackageEntry.id == entry_id,
                SignalPackageEntry.package_id == pkg_id,
            ).first()
            if entry:
                try:
                    entry.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Order+saved", status_code=302)


@router.post("/{pkg_id:int}/delete")
async def package_delete(
    pkg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    pkg = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id,
        SignalPackage.is_testing == testing,
    ).first()
    if pkg:
        links = (
            db.query(SerialPackage)
            .filter(SerialPackage.package_id == pkg_id)
            .all()
        )
        blocking_links = [
            link for link in links
            if link.serial and link.serial.is_testing == testing and link.serial.closed_at is None
        ]
        if blocking_links:
            titles = [link.serial.display_title for link in blocking_links[:3]]
            suffix = f" ({', '.join(titles)}" + (", ..." if len(blocking_links) > 3 else "") + ")" if titles else ""
            message = f"Cannot delete '{pkg.name}' because it is assigned to {len(blocking_links)} active or pending serial(s){suffix}. End/delete those serials first."
            db.add(AuditLog(
                user_id=current_user.id,
                action_type="PACKAGE_DELETE_BLOCKED",
                entity_type="SignalPackage",
                entity_id=pkg_id,
                new_value=pkg.name,
                comment=message,
            ))
            db.commit()
            return RedirectResponse(f"/packages?error={quote_plus(message)}", status_code=302)
        closed_links = [link for link in links if link.serial and link.serial.is_testing == testing]
        for link in closed_links:
            db.delete(link)
        db.delete(pkg)
        db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_DELETE",
                        entity_type="SignalPackage", entity_id=pkg_id, new_value=pkg.name,
                        comment=f"Removed {len(closed_links)} closed-serial package reference(s)."))
        db.commit()
    return RedirectResponse("/packages?toast=Package+deleted", status_code=302)


# ── Export / Import ───────────────────────────────────────────────────────────

@router.get("/{pkg_id:int}/export")
async def package_export(
    pkg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    if len(pkg.signals) == 1:
        entry = pkg.signals[0]
        data = _cbm_text_from_entry(entry)
        filename = _safe_filename(entry.signal_name or pkg.name, "signal") + ".txt"
        return StreamingResponse(
            iter([data]),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, entry in enumerate(pkg.signals, start=1):
            filename = _safe_filename(entry.signal_name or f"signal_{i}", f"signal_{i}") + ".txt"
            zf.writestr(filename, _cbm_text_from_entry(entry))
        zf.writestr(
            "project_range_package.json",
            json.dumps(_package_to_dict(pkg), indent=2),
        )
    buffer.seek(0)
    filename = _safe_filename(pkg.name, "signal_package") + "_cbm_configs.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/import", response_class=HTMLResponse)
async def package_import_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "package_import.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "page": "packages",
        "package": None,
        "error": None,
        **_dropdown_lists(db),
    })


@router.post("/import")
async def package_import_submit(
    request: Request,
    package_name: str = Form(""),
    description: str = Form(""),
    band: str = Form(""),
    antenna: str = Form(""),
    tx_lo: Optional[float] = Form(None),
    rx_lo: Optional[float] = Form(None),
    ttf: Optional[float] = Form(None),
    ttf_direction: str = Form("+"),
    freq_unit: str = Form("MHz"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    error = None
    try:
        files = await _uploaded_signal_files(request)
        if len(files) == 1 and files[0][0].lower().endswith(".json"):
            data = _validated_json_package(files[0][1])
            return _import_json_package(data, files[0][0], db, current_user)

        entries = _entries_from_uploaded_files(files)

        pkg_name = package_name.strip()
        if not pkg_name:
            pkg_name = entries[0]["signal_name"] if len(entries) == 1 else f"CBM Import {datetime.utcnow().strftime('%Y%m%d %H%MZ')}"
        pkg = SignalPackage(
            name=pkg_name,
            description=description.strip() or "Imported from CBM-400 signal configuration file(s).",
            band=band or None,
            antenna=antenna.strip() or None,
            tx_lo=tx_lo,
            rx_lo=rx_lo,
            ttf=ttf,
            ttf_direction=ttf_direction or "+",
            freq_unit=freq_unit or "MHz",
            created_by_id=current_user.id,
            is_testing=is_testing_state(db),
        )
        db.add(pkg)
        db.flush()
        testing = is_testing_state(db)
        _add_imported_entries_to_package(pkg, entries, db, testing, _package_rf_values(pkg=pkg))
        db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_IMPORT",
                        entity_type="SignalPackage", entity_id=pkg.id, new_value=pkg.name))
        db.commit()
        return RedirectResponse(f"/packages/{pkg.id}?toast=CBM+config+imported", status_code=302)
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "package_import.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "page": "packages",
        "package": None,
        "error": error,
        **_dropdown_lists(db),
    })


@router.get("/{pkg_id:int}/import", response_class=HTMLResponse)
async def package_import_existing_page(
    pkg_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id,
        SignalPackage.is_testing == is_testing_state(db),
    ).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    return templates.TemplateResponse(request, "package_import.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "page": "packages",
        "package": pkg,
        "error": None,
        **_dropdown_lists(db),
    })


@router.post("/{pkg_id:int}/import")
async def package_import_existing_submit(
    pkg_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    pkg = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id,
        SignalPackage.is_testing == testing,
    ).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)

    try:
        files = await _uploaded_signal_files(request)
        entries = _entries_from_uploaded_files(files, display_offset=len(pkg.signals))
        imported = _add_imported_entries_to_package(pkg, entries, db, testing, _package_rf_values(pkg=pkg))
        if imported == 0:
            raise ValueError("No named signals were found to import.")
        pkg.updated_at = datetime.utcnow()
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="PACKAGE_IMPORT_SIGNALS",
            entity_type="SignalPackage",
            entity_id=pkg.id,
            new_value=f"{imported} signal(s) imported into {pkg.name}",
        ))
        db.commit()
        return RedirectResponse(f"/packages/{pkg.id}?toast={imported}+signal(s)+imported", status_code=302)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(request, "package_import.html", {
            "user": current_user,
            "range_state": get_current_range_state(db),
            "page": "packages",
            "package": pkg,
            "error": str(e),
            **_dropdown_lists(db),
        })


def _import_json_package(data: dict, filename: str, db: Session, current_user: User):
    try:
        rf = data.get("rf_config", {}) or {}
        pkg = SignalPackage(
            name=str(data.get("name", filename or "Imported Package")).strip(),
            description=str(data.get("description", "")).strip() or None,
            band=str(rf.get("band", "")).strip() or None,
            antenna=str(rf.get("antenna", "")).strip() or None,
            # Accept legacy "buc"/"lo" keys from packages exported before the rename.
            tx_lo=_float_or_none(rf.get("tx_lo", rf.get("buc"))),
            rx_lo=_float_or_none(rf.get("rx_lo", rf.get("lo"))),
            ttf=_float_or_none(rf.get("ttf")),
            ttf_direction=str(rf.get("ttf_direction", "+")) or "+",
            freq_unit=str(rf.get("freq_unit", "MHz")) or "MHz",
            created_by_id=current_user.id,
            is_testing=is_testing_state(db),
        )
        db.add(pkg)
        db.flush()
        testing = is_testing_state(db)
        for fields in _dict_to_entries(data):
            if not fields["signal_name"]:
                continue
            device = _cbm_source_device(db, fields.get("source") or "", testing)
            if device:
                fields["source"] = device.name
                fields["cbm_device_id"] = device.id
            db.add(SignalPackageEntry(package_id=pkg.id, **fields))
        db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_IMPORT",
                        entity_type="SignalPackage", entity_id=pkg.id, new_value=pkg.name))
        db.commit()
        return RedirectResponse(f"/packages/{pkg.id}?toast=Package+imported", status_code=302)
    except Exception:
        db.rollback()
        raise

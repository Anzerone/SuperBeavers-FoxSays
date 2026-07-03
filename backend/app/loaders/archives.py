"""Рекурсивная распаковка вложенных архивов реального корпуса.

Корпус «Научный клубок» приходит как один большой .zip, внутри которого
встречаются вложенные .zip / .rar и многотомные архивы (.001 / .002 / .003).
Модуль разворачивает всё это в staging-папки рядом с архивами, аккуратно
декодируя русские имена файлов (cp866 без UTF-8-флага) и защищаясь от
zip-бомб, path traversal и циклов.

Зависимости мягкие:
  * .zip           — стандартный zipfile (всегда доступен);
  * .rar           — rarfile + бинарь unrar/unar/bsdtar, иначе patoolib,
                     иначе аккуратно логируем и пропускаем;
  * .001/.002/...  — склеиваем тома в один файл, определяем тип по сигнатуре.

Идемпотентность: если рядом с архивом уже есть распакованная папка
«<имя>.__unpacked__», повторно не распаковываем.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from loguru import logger

from app.config import settings

UNPACK_SUFFIX = ".__unpacked__"

# сигнатуры для склеенных многотомников
_MAGIC = {
    b"PK\x03\x04": "zip",
    b"PK\x05\x06": "zip",       # пустой zip
    b"Rar!\x1a\x07": "rar",     # RAR 4/5
    b"7z\xbc\xaf\x27\x1c": "7z",
}


# --------------------------------------------------------------------------
# Имена файлов внутри zip
# --------------------------------------------------------------------------

def decode_zip_name(info: zipfile.ZipInfo) -> str:
    """Возвращает корректное имя entry.

    Если установлен бит 0x800 — имя уже в UTF-8. Иначе zipfile декодирует его
    как cp437; в русских архивах это на самом деле cp866 — перекодируем.
    """
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


# --------------------------------------------------------------------------
# Guard-хелперы
# --------------------------------------------------------------------------

def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_first_volume(path: Path) -> bool:
    """.001 первого тома многотомного архива."""
    return path.suffix.lower() == ".001"


def _is_archive(path: Path) -> bool:
    return path.suffix.lower() in (".zip", ".rar", ".7z") or _is_first_volume(path)


# --------------------------------------------------------------------------
# ZIP
# --------------------------------------------------------------------------

def unpack_zip(path: Path, dest: Path, budget_mb: int | None = None) -> int:
    """Распаковывает zip в dest с cp866-именами и защитой от бомб/traversal."""
    budget = (budget_mb or settings.max_uncompressed_mb) * 1024 * 1024
    written = 0
    count = 0
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = decode_zip_name(info)
                out = dest / name
                if not _is_within(dest, out):
                    logger.warning(f"skip path-traversal entry: {name}")
                    continue
                written += info.file_size
                if written > budget:
                    logger.warning(f"budget {budget_mb} MB exceeded in {path.name}, stopping")
                    break
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                count += 1
    except (zipfile.BadZipFile, OSError) as e:
        logger.warning(f"bad zip {path}: {e}")
    return count


# --------------------------------------------------------------------------
# RAR (опционально)
# --------------------------------------------------------------------------

def unpack_rar(path: Path, dest: Path) -> int:
    """Пытается распаковать rar. Требует rarfile+unrar или patoolib.

    При отсутствии инструментов — предупреждает и возвращает 0 (не падает).
    """
    dest.mkdir(parents=True, exist_ok=True)
    try:
        import rarfile  # type: ignore

        with rarfile.RarFile(path) as rf:
            rf.extractall(path=dest)
            return sum(1 for _ in dest.rglob("*") if _.is_file())
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"rarfile failed for {path.name}: {e}")
    try:
        import patoolib  # type: ignore

        patoolib.extract_archive(str(path), outdir=str(dest), verbosity=-1)
        return sum(1 for _ in dest.rglob("*") if _.is_file())
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"patoolib failed for {path.name}: {e}")
    logger.warning(
        f"RAR не распакован (нет unrar/unar/7z/patoolib): {path.name} — пропущен"
    )
    return 0


# --------------------------------------------------------------------------
# Многотомные архивы .001/.002/...
# --------------------------------------------------------------------------

def _collect_volumes(first: Path) -> list[Path]:
    stem = first.with_suffix("")  # отбрасываем .001
    vols = []
    i = 1
    while True:
        v = stem.with_suffix(f".{i:03d}")
        if v.exists():
            vols.append(v)
            i += 1
        else:
            break
    return vols


def join_split_volumes(first: Path, work: Path):
    """Склеивает тома .001/.002/... в один файл в папке work. Возвращает путь."""
    vols = _collect_volumes(first)
    if not vols:
        return None
    work.mkdir(parents=True, exist_ok=True)
    joined = work / (first.with_suffix("").name + ".joined")
    try:
        with open(joined, "wb") as out:
            for v in vols:
                with open(v, "rb") as f:
                    shutil.copyfileobj(f, out)
    except OSError as e:
        logger.warning(f"failed to join volumes for {first.name}: {e}")
        return None
    return joined


def _sniff(path: Path):
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    for magic, kind in _MAGIC.items():
        if head.startswith(magic):
            return kind
    return None


# --------------------------------------------------------------------------
# Диспетчер + рекурсия
# --------------------------------------------------------------------------

def unpack_archive(path: Path, dest: Path, work: Path) -> int:
    """Распаковывает один архив (любого поддерживаемого типа) в dest."""
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return unpack_zip(path, dest)
    if suffix == ".rar":
        return unpack_rar(path, dest)
    if _is_first_volume(path):
        joined = join_split_volumes(path, work)
        if not joined:
            return 0
        kind = _sniff(joined)
        try:
            if kind == "zip":
                return unpack_zip(joined, dest)
            if kind == "rar":
                rar_path = joined.with_suffix(".rar")
                joined.rename(rar_path)
                return unpack_rar(rar_path, dest)
            logger.warning(f"unknown joined archive type for {path.name}: {kind}")
            return 0
        finally:
            for p in (joined, joined.with_suffix(".rar")):
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
    logger.warning(f"unsupported archive: {path.name}")
    return 0


def unpack_recursive(root, max_depth: int | None = None) -> dict:
    """Рекурсивно распаковывает все вложенные архивы под root.

    Каждый архив «X.zip» разворачивается в соседнюю папку «X.zip.__unpacked__/».
    Затем содержимое сканируется на новые архивы — и так до max_depth.
    Идемпотентно: уже распакованные архивы (папка существует) пропускаются.
    """
    root = Path(root)
    max_depth = max_depth if max_depth is not None else settings.max_archive_depth
    work = root / ".__archive_tmp__"
    stats = {"archives": 0, "files_extracted": 0, "skipped": 0, "depth": 0}
    seen = set()

    frontier = [root]
    depth = 0
    while frontier and depth < max_depth:
        next_frontier = []
        for base in frontier:
            for p in sorted(Path(base).rglob("*")):
                if not p.is_file() or not _is_archive(p):
                    continue
                # служебную папку склейки томов не трогаем; вложенные архивы
                # внутри уже распакованных .__unpacked__ обрабатывать НУЖНО —
                # от повторов защищают seen + проверка dest.exists()
                if ".__archive_tmp__" in str(p):
                    continue
                # тома .002+ обрабатываются вместе с .001
                sfx = p.suffix.lower()
                if sfx.startswith(".") and sfx[1:].isdigit() and not _is_first_volume(p):
                    continue
                key = str(p.resolve())
                if key in seen:
                    continue
                seen.add(key)
                dest = p.parent / (p.name + UNPACK_SUFFIX)
                if dest.exists():
                    stats["skipped"] += 1
                    next_frontier.append(dest)
                    continue
                dest.mkdir(parents=True, exist_ok=True)
                n = unpack_archive(p, dest, work)
                if n:
                    stats["archives"] += 1
                    stats["files_extracted"] += n
                    next_frontier.append(dest)
                else:
                    try:
                        dest.rmdir()
                    except OSError:
                        pass
        frontier = next_frontier
        depth += 1
        stats["depth"] = depth

    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    logger.info(
        f"Archives unpacked: {stats['archives']} arc, "
        f"{stats['files_extracted']} files, depth={stats['depth']}, "
        f"skipped={stats['skipped']}"
    )
    return stats

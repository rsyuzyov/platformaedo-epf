#!/usr/bin/env python3
"""Проверки исходников обработки, не требующие платформы 1С.

Собрать .epf без конфигуратора нельзя, поэтому в CI проверяется то, что читается из самих XML и BSL:
формат выгрузки, версия обработки и её связь с версией вендора, разбираемость XML, BOM текстовых
макетов, отсутствие в публичном дереве следов конкретной базы и сохранность ссылочных типов конфигурации.

Запуск:
    python build/checks.py            # все проверки
    python build/checks.py --version  # напечатать версию обработки и выйти
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

# Формат выгрузки платформы 8.3.21: исходники собирает любая платформа 8.3.21 и новее, собранный файл
# открывается у всех, кто на 8.3.21 и выше. Выгрузка другой платформой молча поменяет формат.
DUMP_FORMAT = "2.14"

OBJECT_MODULE = os.path.join("ОФД_ЭДО", "Ext", "ObjectModule.bsl")
# В «Версии» карточки БСП (Строка 10) - версия вендора; наша сборка - в «Информации»: «... Сборка 1.0.5.3.8.6 (...)».
VENDOR_VERSION_PATTERN = re.compile(r'РегистрационныеДанные\.Вставить\("Версия",\s*"([^"]*)"\)')
BUILD_VERSION_PATTERN = re.compile(r'РегистрационныеДанные\.Вставить\("Информация",\s*"[^"]*Сборка (\d+(?:\.\d+)+)[^"]*"\)')
VERSION_FIELD_LENGTH = 10

HYGIENE_PATTERNS = [
    ("имя внутреннего домена", re.compile(r"\b[a-z0-9-]+\.(?:local|lan|corp)\b", re.IGNORECASE)),
    # 10.0.0.0/8 не проверяется: версии конфигураций 1С («БП 10.3.88.3») от таких адресов неотличимы.
    ("приватный IP-адрес", re.compile(r"\b(?:192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
    ("непустой отпечаток КЭП в коде", re.compile(r"Отпечаток\w*\s*=\s*\"[0-9A-Za-z+/=]{16,}\"")),
    ("пароль строкой", re.compile(r"(?:Пароль|Password)\s*=\s*\"[^\"]{3,}\"", re.IGNORECASE)),
]

TEXT_SUFFIXES = (".xml", ".bsl", ".txt", ".html")


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def src_dir() -> str:
    return os.path.join(repo_root(), "src")


def iter_files(root: str):
    for directory, _subdirectories, file_names in os.walk(root):
        for file_name in sorted(file_names):
            yield os.path.join(directory, file_name)


def rel(path: str) -> str:
    return os.path.relpath(path, repo_root()).replace(os.sep, "/")


class Report:
    def __init__(self) -> None:
        self.failed = False

    def ok(self, message: str) -> None:
        print("  OK   " + message)

    def fail(self, message: str) -> None:
        self.failed = True
        print("  FAIL " + message)

    def stage(self, title: str) -> None:
        print("==> " + title)


def git(*arguments: str) -> tuple[int, str]:
    process = subprocess.run(("git",) + arguments, cwd=repo_root(), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    return process.returncode, process.stdout.strip()


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def read_registration(pattern: re.Pattern, report: Report | None, title: str) -> str | None:
    path = os.path.join(src_dir(), OBJECT_MODULE)
    try:
        with open(path, "r", encoding="utf-8-sig") as module_file:
            match = pattern.search(module_file.read())
    except OSError:
        match = None
    if match is None:
        if report:
            report.fail("в %s не найдено: %s" % (rel(path), title))
        return None
    return match.group(1)


def read_version(report: Report | None = None) -> str | None:
    """Наша сборка из «Информации» СведенияОВнешнейОбработке()."""
    return read_registration(BUILD_VERSION_PATTERN, report, "«Сборка N.N.N.N.N.N» в РегистрационныеДанные «Информация»")


def vendor_base() -> str | None:
    """Версия вендора, на которой стоит HEAD: ближайший тег vendor/* в истории."""
    code, output = git("describe", "--tags", "--match", "vendor/*", "--abbrev=0")
    if code != 0 or not output.startswith("vendor/"):
        return None
    return output[len("vendor/"):]


def check_version(report: Report) -> str | None:
    """Наша версия = версия вендора + номер нашей сборки: 1.0.5.3.8.1, 1.0.5.3.8.2 и т. д."""
    report.stage("версия обработки")
    version = read_version(report)
    vendor_version = read_registration(VENDOR_VERSION_PATTERN, report, "РегистрационныеДанные «Версия»")
    if version is None or vendor_version is None:
        return None
    if len(vendor_version) > VERSION_FIELD_LENGTH:
        report.fail("«Версия» %r длиннее %d символов — БСП обрежет её в карточке" % (vendor_version, VERSION_FIELD_LENGTH))
        return None
    if version.rsplit(".", 1)[0] != vendor_version:
        report.fail("«Версия» %s не совпадает с базой сборки %s" % (vendor_version, version))
        return None
    if not re.fullmatch(r"\d+(?:\.\d+){5}", version):
        report.fail("версия %r не в формате <версия вендора N.N.N.N.N>.<номер сборки>" % version)
        return None
    base = vendor_base()
    if base is None:
        report.ok("версия %s (теги vendor/* недоступны — база не сверена)" % version)
        return version
    if version.rsplit(".", 1)[0] != base:
        report.fail("версия %s, а код стоит на вендоре %s — база версии должна быть %s" % (version, base, base))
        return None
    report.ok("версия %s на базе вендора %s" % (version, base))
    return version


def check_dump_format(report: Report) -> None:
    report.stage("версия формата выгрузки")
    seen: dict[str, list[str]] = {}
    for path in iter_files(src_dir()):
        if not path.endswith(".xml"):
            continue
        try:
            value = ET.parse(path).getroot().get("version")
        except ET.ParseError:
            continue
        if value:
            seen.setdefault(value, []).append(rel(path))
    if not seen:
        report.fail("ни в одном XML нет атрибута version — дерево выгрузки не опознано")
        return
    for value, files in sorted(seen.items()):
        if value == DUMP_FORMAT:
            report.ok("формат %s — %d файл(ов)" % (value, len(files)))
        else:
            report.fail("формат %s вместо %s в %d файле(ах), первый — %s; выгружать только платформой 8.3.21"
                        % (value, DUMP_FORMAT, len(files), files[0]))


def check_text_template_bom(report: Report) -> None:
    """Без BOM ПолучитьМакет().ПолучитьТекст() читает текстовый макет как ANSI."""
    report.stage("BOM у текстовых макетов")
    checked = missing = 0
    for path in iter_files(src_dir()):
        if not path.endswith(".txt") or os.sep + "Templates" + os.sep not in path:
            continue
        checked += 1
        with open(path, "rb") as template_file:
            if template_file.read(3) != b"\xef\xbb\xbf":
                missing += 1
                report.fail("%s: нет BOM — макет прочитается как ANSI" % rel(path))
    if checked and not missing:
        report.ok("BOM на месте — %d текстовых макетов" % checked)
    elif not checked:
        report.ok("текстовых макетов нет")


def check_xml_parses(report: Report) -> None:
    report.stage("разбор XML")
    total = 0
    for path in iter_files(src_dir()):
        if not path.endswith(".xml"):
            continue
        total += 1
        try:
            ET.parse(path)
        except ET.ParseError as parse_error:
            report.fail("%s: %s" % (rel(path), parse_error))
    if total:
        report.ok("разобрано %d XML" % total)
    else:
        report.fail("в src не найдено ни одного XML")


def check_hygiene(report: Report) -> None:
    report.stage("гигиена публичного дерева")
    hits = 0
    for path in iter_files(src_dir()):
        if not path.lower().endswith(TEXT_SUFFIXES):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig", errors="strict") as source_file:
                text = source_file.read()
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for title, pattern in HYGIENE_PATTERNS:
                match = pattern.search(line)
                if match:
                    hits += 1
                    report.fail("%s:%d — %s: %s" % (rel(path), line_number, title, match.group(0)[:80]))
    if not hits:
        report.ok("следов конкретной базы не найдено")


CONFIG_TYPE_PATTERN = re.compile(r"cfg:([A-Za-z]+Ref)\.([^<\"\s]+)")
STUB_FOLDERS = {"CatalogRef": "Catalogs", "DocumentRef": "Documents", "EnumRef": "Enums",
                "ChartOfCharacteristicTypesRef": "ChartsOfCharacteristicTypes"}


def config_types_in_texts(texts) -> dict[str, int]:
    counts: dict[str, int] = {}
    for text in texts:
        for kind, name in CONFIG_TYPE_PATTERN.findall(text):
            key = "%s.%s" % (kind, name)
            counts[key] = counts.get(key, 0) + 1
    return counts


def config_types_in_src() -> dict[str, int]:
    texts = []
    for path in iter_files(src_dir()):
        if path.endswith(".xml"):
            with open(path, "r", encoding="utf-8-sig", errors="replace") as source_file:
                texts.append(source_file.read())
    return config_types_in_texts(texts)


def check_stub_covers_types(report: Report, types_in_src: dict[str, int]) -> None:
    """Тип конфигурации, которого нет в заглушке, при выгрузке и сборке молча превращается в строку."""
    report.stage("заглушка конфигурации покрывает типы исходников")
    stub_dir = os.path.join(repo_root(), "build", "stub-config")
    missing = []
    for key in sorted(types_in_src):
        kind, name = key.split(".", 1)
        folder = STUB_FOLDERS.get(kind)
        if folder is None or not os.path.exists(os.path.join(stub_dir, folder, name + ".xml")):
            missing.append(key)
    if missing:
        report.fail("нет в build/stub-config: %s — добавить объекты в заглушку" % ", ".join(missing))
    else:
        report.ok("все %d типов есть в заглушке" % len(types_in_src))


def check_types_not_lost(report: Report, types_in_src: dict[str, int]) -> None:
    """Ссылочных типов в src не меньше, чем у вендора: потеря типа ломает формы у пользователя."""
    report.stage("ссылочные типы не потеряны относительно вендора")
    base = vendor_base()
    if base is None:
        report.ok("теги vendor/* недоступны — сравнение пропущено")
        return
    code, listing = git("grep", "-h", "-o", "-E", r"cfg:[A-Za-z]+Ref\.[^<\" ]+", "vendor/" + base, "--", "src")
    vendor_types = config_types_in_texts(listing.splitlines()) if code == 0 else {}
    lost = ["%s (%d → %d)" % (key, count, types_in_src.get(key, 0))
            for key, count in sorted(vendor_types.items()) if types_in_src.get(key, 0) < count]
    if lost:
        report.fail("меньше, чем у вендора %s: %s" % (base, ", ".join(lost)))
    else:
        report.ok("%d ссылок на %d типов, у вендора %s — %d" % (sum(types_in_src.values()), len(types_in_src),
                                                              base, sum(vendor_types.values())))


def last_release_tag() -> str | None:
    code, output = git("tag", "--list", "v*", "--sort=-v:refname")
    if code != 0:
        return None
    for line in output.splitlines():
        if re.fullmatch(r"v\d+(?:\.\d+){5}", line.strip()):
            return line.strip()
    return None


def check_version_bumped(report: Report, version: str | None) -> None:
    """Изменился src — версия обязана быть выше последнего релиза: две сборки с одним номером неотличимы."""
    report.stage("версия поднята относительно последнего релиза")
    if version is None:
        report.fail("версия не прочитана — проверка пропущена")
        return
    tag = last_release_tag()
    if tag is None:
        report.ok("релизов ещё нет — сравнивать не с чем")
        return
    code, _ = git("diff", "--quiet", tag, "HEAD", "--", "src")
    if code == 0:
        report.ok("src не менялся с %s" % tag)
    elif code != 1:
        report.ok("сравнение с %s недоступно (нет полной истории) — пропущено" % tag)
    elif version_tuple(version) <= version_tuple(tag[1:]):
        report.fail("src изменён после %s, а сборка осталась %s — поднять «Сборка» в СведенияОВнешнейОбработке"
                    % (tag, version))
    else:
        report.ok("%s > %s, src изменён — версия поднята" % (version, tag))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true", help="напечатать версию обработки и выйти")
    arguments = parser.parse_args()

    if arguments.version:
        version = read_version()
        if version is None:
            print("версия не прочитана", file=sys.stderr)
            return 1
        print(version)
        return 0

    report = Report()
    version = check_version(report)
    check_dump_format(report)
    check_text_template_bom(report)
    check_xml_parses(report)
    check_hygiene(report)
    types_in_src = config_types_in_src()
    check_stub_covers_types(report, types_in_src)
    check_types_not_lost(report, types_in_src)
    check_version_bumped(report, version)
    print()
    print("проверки НЕ пройдены" if report.failed else "проверки пройдены")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())

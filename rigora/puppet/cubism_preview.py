"""Preview a Cubism ``.model3.json`` import without the Cubism SDK.

Reads only the JSON manifest and its sidecar files, so the preview works
on any machine and never loads native code. It lists every referenced
file, whether it exists, and each difference the import will produce:
files the converter skips, motion curves the runtime does not model,
duplicates that a merge leaves out, and whether full conversion can run.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from rigora.puppet.cubism_import_common import CubismFormatError, _read_json
from rigora.puppet.document import PuppetDocument
from rigora.puppet.import_report import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    ImportDifference,
)

MODE_CONVERT = "convert"
MODE_MERGE = "merge"


@dataclass(frozen=True)
class CubismReference:
    """One file named by the manifest."""

    kind: str
    path: str
    exists: bool
    name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CubismImportPreview:
    source: str
    mode: str
    references: tuple[CubismReference, ...]
    motion_names: tuple[str, ...]
    expression_names: tuple[str, ...]
    hit_area_ids: tuple[str, ...]
    differences: tuple[ImportDifference, ...]
    sdk_library: str | None

    @property
    def blocking(self) -> tuple[ImportDifference, ...]:
        return tuple(d for d in self.differences if d.severity == SEVERITY_ERROR)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "mode": self.mode,
            "references": [ref.to_dict() for ref in self.references],
            "motions": list(self.motion_names),
            "expressions": list(self.expression_names),
            "hit_areas": list(self.hit_area_ids),
            "differences": [d.to_dict() for d in self.differences],
            "sdk_library": self.sdk_library,
        }


def preview_cubism_model(
    path: str | Path,
    *,
    document: PuppetDocument | None = None,
    sdk_library: str | Path | None = None,
) -> CubismImportPreview:
    """Describe importing ``path``.

    With ``document`` the preview describes merging the manifest's motions,
    expressions and metadata into it; without one, a full conversion through
    the Cubism Core library. ``sdk_library`` overrides the library search;
    the default uses the same search as the converter but never loads it.
    Raises :class:`CubismFormatError` for an unreadable manifest.
    """
    source = Path(path)
    try:
        manifest = _read_json(source)
    except FileNotFoundError as exc:
        raise CubismFormatError(f"{source} does not exist") from exc
    if not isinstance(manifest, dict):
        raise CubismFormatError(f"{source}: manifest must be a JSON object")
    mode = MODE_MERGE if document is not None else MODE_CONVERT
    scan = _ManifestScan(source.parent, manifest, mode)
    scan.run()
    library = None
    if mode == MODE_CONVERT:
        library = _locate_library(sdk_library)
        scan.conversion_differences(library)
    else:
        scan.merge_differences(document)
    return CubismImportPreview(
        source=str(source), mode=mode, references=tuple(scan.references),
        motion_names=tuple(scan.motion_names), expression_names=tuple(scan.expression_names),
        hit_area_ids=tuple(scan.hit_area_ids), differences=tuple(scan.differences),
        sdk_library=str(library) if library else None,
    )


def _locate_library(explicit: str | Path | None) -> Path | None:
    from rigora.puppet.cubism_native_bridge import find_dll
    return find_dll(explicit)


class _ManifestScan:
    def __init__(self, base: Path, manifest: dict, mode: str) -> None:
        self.base = base
        self.manifest = manifest
        self.refs = manifest.get("FileReferences") or {}
        self.mode = mode
        self.references: list[CubismReference] = []
        self.differences: list[ImportDifference] = []
        self.motion_names: list[str] = []
        self.motion_params: set[str] = set()
        self.expression_names: list[str] = []
        self.hit_area_ids: list[str] = []

    # ---- references --------------------------------------------------------

    def _reference(self, kind: str, ref: str, name: str = "") -> Path:
        resolved = self.base / ref
        self.references.append(CubismReference(kind, ref, resolved.is_file(), name))
        return resolved

    def _add(self, code: str, subject: str, detail: str, severity: str = SEVERITY_WARNING) -> None:
        self.differences.append(ImportDifference(code, subject, detail, severity))

    def run(self) -> None:
        moc = self.refs.get("Moc")
        if isinstance(moc, str) and moc:
            self._reference("moc", moc)
        for texture in self.refs.get("Textures") or []:
            if isinstance(texture, str):
                self._reference("texture", texture)
        self._scan_motions()
        self._scan_expressions()
        for key, kind in (("Physics", "physics"), ("Pose", "pose"),
                          ("DisplayInfo", "display_info"), ("UserData", "user_data")):
            ref = self.refs.get(key)
            if isinstance(ref, str) and ref:
                self._reference(kind, ref)
        for entry in self.manifest.get("HitAreas") or []:
            if isinstance(entry, dict) and isinstance(entry.get("Id"), str):
                self.hit_area_ids.append(str(entry.get("Name") or entry["Id"]))
        self._missing_sidecars()

    def _scan_motions(self) -> None:
        motions = self.refs.get("Motions") or {}
        if not isinstance(motions, dict):
            self._add("motions_malformed", "Motions", "motion list is not an object; ignored")
            return
        for group, entries in motions.items():
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict) and isinstance(entry.get("File"), str):
                    self._scan_motion_entry(str(group), entry)

    def _scan_motion_entry(self, group: str, entry: dict) -> None:
        file_ref = entry["File"]
        name = f"{group}/{Path(file_ref).stem.removesuffix('.motion3')}"
        path = self._reference("motion", file_ref, name)
        sound = entry.get("Sound")
        if isinstance(sound, str) and sound:
            self._reference("sound", sound, name)
        if not path.is_file():
            return
        try:
            curves = (json.loads(path.read_text(encoding="utf-8-sig")).get("Curves") or [])
        except (ValueError, AttributeError, OSError):
            self._add("motion_invalid", name, f"{file_ref} is not readable motion JSON",
                      SEVERITY_ERROR if self.mode == MODE_MERGE else SEVERITY_WARNING)
            return
        self.motion_names.append(name)
        targets = Counter(c.get("Target") for c in curves if isinstance(c, dict))
        self.motion_params.update(
            c["Id"] for c in curves
            if isinstance(c, dict) and c.get("Target") == "Parameter"
            and isinstance(c.get("Id"), str))
        skipped = {str(t): n for t, n in targets.items() if t != "Parameter"}
        if skipped:
            listing = ", ".join(f"{n} {t}" for t, n in sorted(skipped.items()))
            self._add("motion_curves_skipped", name,
                      f"curves not modelled by the runtime are skipped: {listing}")

    def _scan_expressions(self) -> None:
        for entry in self.refs.get("Expressions") or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("File"), str):
                continue
            file_ref = entry["File"]
            name = str(entry.get("Name") or Path(file_ref).stem.removesuffix(".exp3"))
            path = self._reference("expression", file_ref, name)
            # The converter also looks under exp/; the merge does not.
            fallback = self.mode == MODE_CONVERT and (self.base / "exp" / file_ref).is_file()
            if path.is_file() or fallback:
                self.expression_names.append(name)

    def _missing_sidecars(self) -> None:
        for ref in self.references:
            if ref.exists or ref.kind == "moc":
                continue
            if ref.kind == "expression" and ref.name in self.expression_names:
                continue
            fails_merge = self.mode == MODE_MERGE and ref.kind in (
                "motion", "expression", "physics", "pose", "display_info")
            self._add(
                f"{ref.kind}_missing", ref.name or ref.path,
                f"{ref.path} not found" + ("; the merge will stop" if fails_merge else
                                            "; skipped"),
                SEVERITY_ERROR if fails_merge else SEVERITY_WARNING)
        if any(ref.kind == "user_data" for ref in self.references):
            self._add("user_data_ignored", "UserData",
                      "user data annotations are not imported", SEVERITY_INFO)

    # ---- mode-specific -----------------------------------------------------

    def conversion_differences(self, library: Path | None) -> None:
        moc = [ref for ref in self.references if ref.kind == "moc"]
        if not moc:
            self._add("moc_missing", "Moc", "manifest names no .moc3; nothing to convert",
                      SEVERITY_ERROR)
        elif not moc[0].exists:
            self._add("moc_missing", moc[0].path, f"{moc[0].path} not found", SEVERITY_ERROR)
        if library is None:
            self._add("sdk_unavailable", "Cubism Core",
                      "Cubism Core library not found; full conversion cannot run. "
                      "Place the SDK under ./sdk or set CUBISM_CORE_DLL", SEVERITY_ERROR)
        self._add("keyforms_sampled", "Moc",
                  "deformation is sampled per parameter and blended linearly; "
                  "cross-parameter keyform interactions are not reproduced", SEVERITY_INFO)
        if any(ref.kind == "pose" for ref in self.references):
            self._add("pose_not_converted", "Pose",
                      "full conversion does not read pose groups; merge the .model3.json "
                      "into the converted document to add them")
        listed = {(self.base / ref.path).resolve()
                  for ref in self.references if ref.kind == "motion"}
        motions_dir = self.base / "motions"
        extra = [path for path in sorted(motions_dir.glob("*.motion3.json"))
                 if path.resolve() not in listed] if motions_dir.is_dir() else []
        if extra:
            self._add("unlisted_motions_added", "motions/",
                      f"{len(extra)} motion file(s) missing from the manifest join group Idle",
                      SEVERITY_INFO)

    def merge_differences(self, document: PuppetDocument) -> None:
        self._add("mesh_not_imported", "Moc",
                  "merging keeps the open document's drawables; .moc3 and textures are not used",
                  SEVERITY_INFO)
        existing = {m.name for m in document.motions}
        for name in self.motion_names:
            if name in existing:
                self._add("duplicate_motion_skipped", name,
                          "a motion with this name already exists; the incoming one is skipped")
        existing = {e.name for e in document.expressions}
        for name in self.expression_names:
            if name in existing:
                self._add("duplicate_expression_skipped", name,
                          "an expression with this name exists; the incoming one is skipped")
        drawables = {d.id for d in document.drawables}
        for entry in self.manifest.get("HitAreas") or []:
            if isinstance(entry, dict) and isinstance(entry.get("Id"), str) \
                    and entry["Id"] not in drawables:
                self._add("hit_area_unbound", str(entry.get("Name") or entry["Id"]),
                          f"drawable '{entry['Id']}' is not in the document; the area is inert")
        parameters = {p.id for p in document.parameters}
        for param in sorted(self.motion_params - parameters):
            self._add("motion_parameter_missing", param,
                      "motions animate this parameter but the document has none; tracks are inert")

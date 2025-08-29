import sys
import yaml
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QBrush, QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout,
    QLabel, QPushButton, QFileDialog,
    QListWidget, QListWidgetItem, QListView, QProgressBar
)

# ----- Load config (rules.yaml) once -----
with open("rules.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f) or {}

# ----- App state -----
selected_folder = None
PLANNED: list[tuple[Path, Path, str]] = []
LAST_MOVES: list[tuple[str, str]] = []  # (final_path, original_path)

# Logs dir
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


# ---------- Helpers ----------
def _resolve_target(src: Path) -> Path:
    """Resolve target folder from CONFIG, support absolute/relative."""
    raw_tgt = CONFIG.get("target")
    if raw_tgt:
        tgt = Path(raw_tgt)
        if not tgt.is_absolute():
            tgt = src / tgt
    else:
        tgt = src / "Organized"
    return tgt


# ---------- Event handlers ----------
def choose_folder():
    """Open a folder picker and update the label."""
    global selected_folder
    folder = QFileDialog.getExistingDirectory(window, "Select Folder")
    if folder:
        selected_folder = folder
        label.setText(f"Selected: {folder}")
        preview.clear()
        preview.addItem("🧚‍♀️:Click \"Preview Moves\" to see how your files will be organized.")
        apply_btn.setEnabled(False)
    else:
        label.setText("No folder selected.")
        preview.clear()
        preview.addItem("🧚‍♀️:Click \"Choose Folder\" and select the folder you want to organize.")


def start_arranging():
    """Plan moves based on rules; show a short summary instead of a long list."""
    if not selected_folder:
        print("No folder selected.")
        return

    src = Path(selected_folder)
    tgt = _resolve_target(src)
    rules = CONFIG.get("rules", [])

    planned: list[tuple[Path, Path, str]] = []
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        # Skip anything already inside target subtree
        if tgt in f.parents:
            continue

        for r in rules:
            exts = {e.lower() for e in r.get("match", {}).get("ext", [])}
            move_to = r.get("action", {}).get("move_to")
            if exts and move_to and f.suffix.lower() in exts:
                dest = tgt / move_to / f.name
                planned.append((f, dest, r.get("name", "rule")))
                break  # first matching rule wins

    if not planned:
        print("No actions planned. Check your rules or folder.")
        preview.clear()
        preview.addItem("No files to move for the current rules.")
        apply_btn.setEnabled(False)
        return

    # Save plan and show summary
    global PLANNED
    PLANNED = planned

    preview.clear()
    preview.addItem(f"🧚‍♀️:Inside: '{tgt}'")
    preview.addItem("Files will be organized into Images / PDFs / Docs / Videos.")
    preview.addItem("If you want to proceed, click \"Apply Moves\".")
    apply_btn.setEnabled(True)


def apply_moves():
    """Execute planned moves; log results; show summary with clickable links; enable Undo."""
    if not PLANNED:
        print("Nothing to apply. Run Preview Moves first.")
        return

    # --- Progress bar: init & show ---
    total = len(PLANNED)
    progress.setRange(0, total)
    progress.setValue(0)
    progress.setFormat("Moving... %p%")
    progress.setVisible(True)

    import shutil

    moved = 0
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    session_moves: list[tuple[str, str]] = []

    # Open log
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"arranger_{ts}.txt"
    lf = open(log_path, "w", encoding="utf-8")
    lf.write(f"[Apply] {ts}\nSource: {selected_folder}\n\n")

    for srcf, dstf, rname in PLANNED:
        dstf.parent.mkdir(parents=True, exist_ok=True)

        # If already exactly at destination (extra safety)
        try:
            if srcf.resolve() == dstf.resolve():
                print(f"Skip already at destination: {srcf}")
                skipped.append(srcf.name)
                lf.write(f"SKIPPED\t{srcf}\n")
                # tick progress for SKIPPED
                progress.setValue(progress.value() + 1)
                QApplication.processEvents()
                continue
        except FileNotFoundError:
            pass

        # Avoid overwrite: add (1), (2), ...
        candidate = dstf
        i = 1
        while candidate.exists():
            candidate = candidate.with_name(f"{dstf.stem} ({i}){dstf.suffix}")
            i += 1

        # Move with error handling
        try:
            shutil.move(str(srcf), str(candidate))
            moved += 1
            print(f"Moved [{rname}] {srcf} -> {candidate}")
            lf.write(f"MOVED\t{srcf} -> {candidate}\n")
            session_moves.append((str(candidate), str(srcf)))  # remember for Undo
        except Exception as e:
            failed.append((srcf.name, type(e).__name__))
            print(f"[FAIL] {srcf} -> {candidate} ({e})")
            lf.write(f"FAILED\t{srcf} -> {candidate} ({type(e).__name__}: {e})\n")

        # tick progress for MOVED or FAILED
        progress.setValue(progress.value() + 1)
        QApplication.processEvents()

    print(f"Done. Moved {moved} files.")

    # Compute target again (safe)
    src = Path(selected_folder)
    tgt = _resolve_target(src)

    # Close log with summary
    lf.write("\nSUMMARY\n")
    lf.write(f"Moved: {moved}  Skipped: {len(skipped)}  Failed: {len(failed)}\n")
    lf.close()

    # Save undo info
    global LAST_MOVES
    LAST_MOVES = session_moves
    undo_btn.setEnabled(bool(LAST_MOVES))

    # Update preview: links + counts
    preview.clear()
    preview.addItem("🎉 All done!")

    # Target link item (blue + underline)
    link = QListWidgetItem(f"🧚‍♀️: Open '{tgt}' (click to open)")
    link.setData(Qt.UserRole, str(tgt))
    link.setForeground(QBrush(QColor("#1a73e8")))
    f = link.font()
    f.setUnderline(True)
    link.setFont(f)
    preview.addItem(link)

    # Log link item
    log_item = QListWidgetItem(f"📝 Log: '{log_path}' (click to open)")
    log_item.setData(Qt.UserRole, str(log_path))
    log_item.setForeground(QBrush(QColor("#1a73e8")))
    g = log_item.font()
    g.setUnderline(True)
    log_item.setFont(g)
    preview.addItem(log_item)

    # Counts
    preview.addItem(f"Moved: {moved}   Skipped: {len(skipped)}   Failed: {len(failed)}")
    preview.addItem("🧚‍♀️:If you don't like these changes, click the 'Undo' button.")

    # --- Progress bar: hide ---
    progress.setVisible(False)

    # Reset plan / buttons
    PLANNED.clear()
    apply_btn.setEnabled(False)


def undo_moves():
    """Undo the last Apply: move files back to where they came from."""
    global LAST_MOVES

    if not LAST_MOVES:
        preview.clear()
        preview.addItem("Nothing to undo.")
        return

    import shutil

    restored = 0
    failed: list[tuple[str, str]] = []

    # Undo in reverse order (safer for nested moves)
    for final_path, original_path in reversed(LAST_MOVES):
        final = Path(final_path)
        original = Path(original_path)
        try:
            original.parent.mkdir(parents=True, exist_ok=True)

            # Avoid overwrite when restoring
            candidate = original
            i = 1
            while candidate.exists():
                candidate = candidate.with_name(f"{original.stem} (undone {i}){original.suffix}")
                i += 1

            shutil.move(str(final), str(candidate))
            restored += 1
        except Exception as e:
            failed.append((final.name, type(e).__name__))

    preview.clear()
    preview.addItem("🧚‍♀️:All changes were undone.")
    preview.addItem(f"Restored: {restored}   Failed: {len(failed)}")
    if failed:
        preview.addItem("Failed to restore:")
        for name, err in failed[:10]:
            preview.addItem(f"  - {name} ({err})")
        if len(failed) > 10:
            preview.addItem(f"  ... and {len(failed) - 10} more")

    LAST_MOVES.clear()
    undo_btn.setEnabled(False)


def on_preview_click(item: QListWidgetItem):
    """Open clicked path if the item carries a path in UserRole."""
    path = item.data(Qt.UserRole)
    if not path:
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# ---------- Build UI ----------
app = QApplication(sys.argv)

window = QWidget()
window.setWindowTitle("💜Tidy PC💜")

layout = QVBoxLayout()

label = QLabel("🤍 Computer a mess? Don’t worry — I’ll clean it up! 🤍")
layout.addWidget(label)

choose_btn = QPushButton("💜 Choose Folder 💜")
layout.addWidget(choose_btn)

start_btn = QPushButton("💜 Preview Moves 💜")
layout.addWidget(start_btn)

apply_btn = QPushButton("💜 Apply Moves 💜")
layout.addWidget(apply_btn)
apply_btn.clicked.connect(apply_moves)
apply_btn.setEnabled(False)

undo_btn = QPushButton("💜 Undo 💜")
layout.addWidget(undo_btn)
undo_btn.setEnabled(False)
undo_btn.clicked.connect(undo_moves)

# NEW: progress bar (above the preview list)
progress = QProgressBar()
progress.setVisible(False)
progress.setTextVisible(True)
layout.addWidget(progress)

preview = QListWidget()
preview.itemClicked.connect(on_preview_click)

# Wrapping / layout behavior
preview.setWordWrap(True)
preview.setTextElideMode(Qt.ElideNone)
preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
preview.setUniformItemSizes(False)
preview.setResizeMode(QListView.Adjust)

# Empty-state hint (gray, unselectable)
hint = QListWidgetItem("🧚‍♀️:Click \"Choose Folder\" and select the folder you want to organize.")
hint.setFlags(Qt.NoItemFlags)
hint.setForeground(QBrush(QColor("#888")))
hint.setTextAlignment(Qt.AlignCenter)
preview.addItem(hint)

preview.setMinimumHeight(220)
layout.addWidget(preview)

# Wire events
choose_btn.clicked.connect(choose_folder)
start_btn.clicked.connect(start_arranging)

window.setLayout(layout)
window.show()

# ---------- Run loop ----------
app.exec()

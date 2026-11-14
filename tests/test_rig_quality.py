"""R2 acceptance helpers: extreme and blended poses keep meshes intact."""
from __future__ import annotations

from rigora.puppet.document import (
    BlendKey,
    Deformer,
    Drawable,
    Parameter,
    ParameterBlend,
    ParameterKey,
    PuppetDocument,
)
from rigora.puppet.rig_quality import check_poses, pose_samples


def doc(fold: float = 0.0) -> PuppetDocument:
    grid = [[[0, 0], [10, 0]], [[0, 10], [10, 10]]]
    folded = [[[0, 0], [10, 0]], [[0, 10], [10 * (1 - fold) - fold * 20, 10]]]
    warp = Deformer("w", "warp", None, ["q"], {"rows": 2, "cols": 2, "grid": grid,
                                               "bounds": [0, 0, 10, 10]})
    return PuppetDocument(
        drawables=[Drawable("q", "t", [(0, 0), (10, 0), (10, 10), (0, 10)], [0, 1, 2, 0, 2, 3],
                            [(0, 0), (1, 0), (1, 1), (0, 1)])],
        deformers=[warp],
        parameters=[Parameter("P", 0, 1, 0, [ParameterKey(0, {"w": {"grid": grid}}),
                                             ParameterKey(1, {"w": {"grid": folded}})]),
                    Parameter("Q", -1, 1, 0)],
        parameter_blends=[ParameterBlend("b", ["P", "Q"], [BlendKey([0, 0])])],
    )


def test_pose_samples_cover_extremes_and_blend_corners():
    labels = [label for label, _ in pose_samples(doc())]
    assert labels[:5] == ["neutral", "P=min", "P=max", "Q=min", "Q=max"]
    assert labels[5:] == ["b:P=0,Q=-1", "b:P=0,Q=1", "b:P=1,Q=-1", "b:P=1,Q=1"]
    assert len(pose_samples(doc(), limit=3)) == 3


def test_intact_rig_is_clean_and_folded_rig_is_reported():
    assert check_poses(doc()).clean
    report = check_poses(doc(fold=1.0))
    assert not report.clean
    assert report.flipped["P=max"] == {"q": 1}
    assert report.to_dict()["clean"] is False

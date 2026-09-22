import json
import unittest
import subprocess
from pathlib import Path
from unittest.mock import Mock

from mounts import MountedImage, MountError, select_partitions


class PartitionSelectionTests(unittest.TestCase):
    def test_selects_labelled_boot_and_largest_linux_root(self):
        value = json.dumps({"blockdevices": [{
            "path": "/dev/loop7",
            "children": [
                {"path": "/dev/loop7p1", "fstype": "vfat", "partlabel": "bootfs", "size": 536870912},
                {"path": "/dev/loop7p2", "fstype": "ext4", "partlabel": "rootfs", "size": 8589934592},
                {"path": "/dev/loop7p3", "fstype": "ext4", "partlabel": "data", "size": 1048576},
            ],
        }]})
        selected = select_partitions(value)
        self.assertEqual(selected.boot, Path("/dev/loop7p1"))
        self.assertEqual(selected.root, Path("/dev/loop7p2"))

    def test_rejects_image_without_required_filesystems(self):
        value = json.dumps({"blockdevices": [{"path": "/dev/loop7", "children": [
            {"path": "/dev/loop7p1", "fstype": "ext4", "size": 100},
        ]}]})
        with self.assertRaises(MountError):
            select_partitions(value)

    def test_rejects_invalid_lsblk_output(self):
        with self.assertRaises(MountError):
            select_partitions("not-json")

    def test_selects_partitions_from_flat_output(self):
        value = json.dumps({"blockdevices": [
            {"path": "/dev/loop7", "fstype": None, "size": 1000},
            {"path": "/dev/loop7p1", "fstype": "vfat", "size": 100},
            {"path": "/dev/loop7p2", "fstype": "ext4", "size": 900},
        ]})
        selected = select_partitions(value)
        self.assertEqual(selected.boot, Path("/dev/loop7p1"))
        self.assertEqual(selected.root, Path("/dev/loop7p2"))

    def test_discovery_requests_tree_without_name_column(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "blockdevices": [{"path": "/dev/loop7", "type": "loop", "children": [
                {"path": "/dev/loop7p1", "type": "part", "fstype": "vfat", "size": 100},
                {"path": "/dev/loop7p2", "type": "part", "fstype": "ext4", "size": 900},
            ]}],
        })))
        mounted = MountedImage(Path("image.img"), Path("mounts"), runner=runner)
        mounted.loop_device = Path("/dev/loop7")
        self.assertEqual(mounted._discover_partitions().root, Path("/dev/loop7p2"))
        command = runner.call_args.args[0]
        self.assertIn("--tree", command)
        self.assertEqual(command[-1], "/dev/loop7")

    def test_error_reports_detected_filesystems(self):
        value = json.dumps({"blockdevices": [
            {"path": "/dev/loop7p1", "type": "part", "fstype": None},
        ]})
        with self.assertRaisesRegex(MountError, r"/dev/loop7p1 \(unknown filesystem\)"):
            select_partitions(value)


if __name__ == "__main__":
    unittest.main()

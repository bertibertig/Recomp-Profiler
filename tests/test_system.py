from recomp_profiler.agent.handlers.system import _parse_lspci_gpus

LSPCI_MM = '''\
00:00.0 "Host bridge" "Intel Corporation" "Xeon E3-1200 v5/E3-1500 v5/6th Gen Core Processor Host Bridge/DRAM Registers" -r07 "Lenovo" "Device 5050"
00:02.0 "VGA compatible controller" "Intel Corporation" "HD Graphics 530" -r06 -p00 "Lenovo" "Device 5050"
02:00.0 "3D controller" "NVIDIA Corporation" "GM108M [GeForce 940MX]" -ra2 "Lenovo" "Device 5050"
'''


def test_parse_lspci_gpus():
    assert _parse_lspci_gpus(LSPCI_MM) == [
        {"name": "HD Graphics 530", "vendor": "Intel Corporation", "source": "lspci"},
        {"name": "GM108M [GeForce 940MX]", "vendor": "NVIDIA Corporation", "source": "lspci"},
    ]

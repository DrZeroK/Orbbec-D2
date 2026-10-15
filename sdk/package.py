"""Build a fresh D2-only runtime from a pinned, user-supplied ARM64 OpenNI SDK."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

SHA256={
 'libOpenNI2.so':'e5cc7f0246a8251ac887ac56e667301210388b1fcd038d99fae22738dabb58b7',
 'OpenNI.ini':'3896e8f831c6a56576e9e93a2e5b3e1d3fa72041e7d01e1d7f23b7cd907e7eff',
 'OpenNI2/Drivers/libOniFile.so':'847beadad9fc2e3ab4dab81b18a7cfdfc420d83091fa5ce07be2e349bdf33334',
 'OpenNI2/Drivers/liborbbec.so':'24e43298e83d74bb3ce8dcf3ca28979e6334603f9d0534542aa5891cc6764e4b',
 'OpenNI2/Drivers/OniFile.ini':'f50a20ca76350f8e5e81b50477714f9a1b1db9b49047f5089b90644526ba9505',
 'OpenNI2/Drivers/orbbec.ini':'b6a1cc4ed8ee62c7c4b2596e43727362ee489bd1733f59633794b005224d1e9b',
}
TABLE=0xf9dc0


def patch_driver(data):
    if hashlib.sha256(data).hexdigest()!=SHA256['OpenNI2/Drivers/liborbbec.so']:
        raise ValueError('unrecognized original driver; no patch applied')
    if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=183:
        raise ValueError('expected little-endian ARM64 ELF')
    pairs=[struct.unpack_from('<HH',data,TABLE+4*i) for i in range(45)]
    if pairs[0]!=(0x2bc5,0x0300) or any(v!=0x2bc5 for v,p in pairs) or (0x2bc5,0x060d) in pairs:
        raise ValueError('unexpected original enumeration table')
    result=bytearray(data)
    struct.pack_into('<H',result,TABLE+2,0x060d)
    assert [i for i,(a,b) in enumerate(zip(data,result)) if a!=b]==[TABLE+2,TABLE+3]
    return bytes(result)


def create(upstream,output,platform_headers=None):
    upstream=upstream.resolve(strict=True)
    source=Path(__file__).resolve().parent
    originals={}
    for name,digest in SHA256.items():
        path=upstream/'libs'/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('upstream file mismatch: '+name)
        originals[name]=path.read_bytes()
    if (upstream/'libs'/'OpenNI2/Drivers').is_symlink():
        raise ValueError('unexpected symlinked driver directory')
    patched=patch_driver(originals['OpenNI2/Drivers/liborbbec.so'])
    # New destination only: never patch or overwrite an installed runtime.
    output.mkdir(parents=True,exist_ok=False)
    for name,data in originals.items():
        path=output/'lib'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(patched if name.endswith('liborbbec.so') else data)
    shutil.copytree(upstream/'Include',output/'include/openni')
    if platform_headers is not None:
        for name in ('OniPlatform.h','OniVersion.h'):
            target=output/'include/openni'/name
            if not target.exists():
                shutil.copy(platform_headers/name,target)
        for name in ('Linux-Arm','Linux-x86'):
            shutil.copytree(platform_headers/name,output/'include/openni'/name)
    shutil.copy(source/'include/d2sdk.h',output/'include/d2sdk.h')
    shutil.copy(source/'README.md',output/'README.md')
    shutil.copytree(source/'examples',output/'examples',ignore=shutil.ignore_patterns('__pycache__'))
    manifest={'schema':'d2-sdk-package/1','version':'0.2.0','platform':'linux-aarch64','upstream_sha256':SHA256,
        'driver_patch':{'file':'lib/OpenNI2/Drivers/liborbbec.so','offset':TABLE+2,
            'before_hex':'0003','after_hex':'0d06','replaces_pid':'0300','supports_pid':'060d',
            'scope':'Dedicated D2 build; legacy PID 0300 support is intentionally replaced.'},
        'performance':'No frame-rate or firmware patch; measured rates remain separate.',
        'files':{str(p.relative_to(output)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.rglob('*') if p.is_file()}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream',type=Path,required=True,help='Original SDK directory containing Include/ and libs/')
    parser.add_argument('--output',type=Path,required=True,help='New output directory; must not already exist')
    parser.add_argument('--platform-headers',type=Path,help='Common platform headers from matching official OpenNI SDK')
    args=parser.parse_args()
    print(json.dumps(create(args.upstream,args.output,args.platform_headers),indent=2))

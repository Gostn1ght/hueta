"""Read real skeleton keyframes for editable RP pictograms; no game capture."""
from pathlib import Path
import struct, math
import numpy as np

def chunks(data):
    p=0
    while p+8<=len(data):
        kind,size=struct.unpack_from('<II',data,p)
        yield kind,data[p+8:p+8+size]
        p+=8+size

def string(data,p):
    end=data.index(0,p)
    return data[p:end].decode('cp1251'),end+1

class Motions:
    def __init__(self, omf, actor):
        d=dict(chunks(Path(omf).read_bytes()))
        meta=d[15];version,parts=struct.unpack_from('<HH',meta);p=4;names={}
        for _ in range(parts):
            _,p=string(meta,p);n=struct.unpack_from('<H',meta,p)[0];p+=2
            for _ in range(n):
                name,p=string(meta,p);bid=struct.unpack_from('<I',meta,p)[0];p+=4;names[bid]=name
        self.bones=[names[i] for i in range(len(names))]
        bone_data=dict(chunks(Path(actor).read_bytes()))[13]
        count=struct.unpack_from('<I',bone_data)[0];p=4;self.parents={}
        for _ in range(count):
            name,p=string(bone_data,p);parent,p=string(bone_data,p);p+=60
            self.parents[name]=parent
        assert set(self.bones)<=set(self.parents)
        self.motions={}
        for i,b in chunks(d[14]):
            if not i:continue
            name,p=string(b,0);self.motions[name]=b[p:]

    def pose(self, name, fraction=.3, matrices=False):
        data=self.motions[name];count=struct.unpack_from('<I',data)[0];p=4
        frame=min(count-1,round(count*fraction));local={}
        for bone in self.bones:
            flags=data[p];p+=1
            if flags&2:
                quat=struct.unpack_from('<4h',data,p);p+=8
            else:
                p+=4;quat=struct.unpack_from('<4h',data,p+frame*8);p+=count*8
            if flags&1:
                p+=4;wide=bool(flags&4);size=6 if wide else 3
                key=np.array(struct.unpack_from('<3h' if wide else '<3b',data,p+frame*size));p+=count*size
                scale=np.array(struct.unpack_from('<3f',data,p));p+=12
                initial=np.array(struct.unpack_from('<3f',data,p));p+=12
                translation=key*scale+initial
            else:
                translation=np.array(struct.unpack_from('<3f',data,p));p+=12
            x,y,z,w=np.array(quat,dtype=float)/32767
            # Quaternion rotation uses the same column-vector basis as Fmatrix.
            rotation=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                               [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                               [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
            matrix=np.eye(4);matrix[:3,:3]=rotation.T;matrix[:3,3]=translation;local[bone]=matrix
        assert p==len(data),(name,p,len(data))
        world={}
        def evaluate(bone):
            if bone not in world:
                parent=self.parents[bone]
                world[bone]=evaluate(parent)@local[bone] if parent else local[bone]
            return world[bone]
        return {bone:evaluate(bone).copy() if matrices else evaluate(bone)[:3,3] for bone in self.bones}

if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]
    motions=Motions(root/'gamma-runtime/gamedata/meshes/actors/stalker_scripts_animation.omf',
                    root/'gamma-runtime/gamedata/meshes/actors/stalker_radseva_series/stalker_monolith_radseva.ogf')
    print(motions.bones)
    print(motions.pose('hand_up_0'))

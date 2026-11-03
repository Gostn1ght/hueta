"""Split original OGF triangles without a Blender import/weld/normal conversion.

Candidate only. Preserve positions, normals, tangents, UVs, materials and winding.
One root / box / positive mass per piece; no game process is executed.
"""
import argparse,collections,hashlib,json,math,re,struct
from pathlib import Path

root=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
ap.add_argument('--template-candidate',type=Path,required=True);ap.add_argument('--only',default='')
a=ap.parse_args();assert not a.out.exists(),'Review or choose a new candidate directory'
a.out.mkdir(parents=True)
models=json.loads((root/'tools/dcp-seat-layouts.json').read_text())
old={r['source']:r for r in json.loads((a.template_candidate/'debris-reviewed-candidate.json').read_text())}

def sha(b):return hashlib.sha256(b).hexdigest()
def chunks(data):
    c={};offset=0
    while offset<len(data):
        tag,n=struct.unpack_from('<II',data,offset);offset+=8
        assert not tag&0x80000000 and offset+n<=len(data) and tag not in c
        c[tag]=data[offset:offset+n];offset+=n
    assert offset==len(data);return c
def packed(c):return b''.join(struct.pack('<II',t,len(b))+b for t,b in c.items())
def string(b,o):
    end=b.index(0,o);return b[o:end].decode('cp1251'),end+1
def classify(name,parents):
    while name:
        if re.search(r'(?:left|right)_wheel\d*$',name) and not name.startswith('stearing_'):return name
        if re.search(r'^(?:back_)?(?:left|right)_door$',name):return name
        if name in {'front_door','back_door','hood','bonnet','trunk'}:return name
        if re.fullmatch(r'(front|back)_door\d',name):return name.split('_door')[0]+'_door'
        name=parents[name]
    return 'body'
def bounds(points):
    lo=[min(v[k] for v in points) for k in range(3)];hi=[max(v[k] for v in points) for k in range(3)]
    centre=[(lo[k]+hi[k])/2 for k in range(3)];half=[max(.015,(hi[k]-lo[k])/2) for k in range(3)]
    radius=math.sqrt(sum(((hi[k]-lo[k])/2)**2 for k in range(3)))
    return lo,hi,centre,half,radius
def header(kind,points):
    lo,hi,centre,_,radius=bounds(points)
    return struct.pack('<BBH10f',4,kind,0,*lo,*hi,*centre,radius)

report=[]
for relative in models:
    if a.only and a.only not in relative:continue
    data=(root/'scripts/netcoop-overlay/client/meshes'/relative).read_bytes();c=chunks(data)
    assert sha(data)==old[relative]['source_sha256']
    n,=struct.unpack_from('<I',c[13]);offset=4;names=[];parents={}
    for _ in range(n):
        name,offset=string(c[13],offset);parent,offset=string(c[13],offset);offset+=60
        names.append(name);parents[name]=parent
    assert offset==len(c[13]) and names[0]=='root'
    groups=collections.defaultdict(lambda:collections.defaultdict(list));total=0
    for child in chunks(c[9]).values():
        mesh=chunks(child);v=mesh[3];kind,count=struct.unpack_from('<II',v);stride=(len(v)-8)//count
        assert stride in {60,64,70,76} and len(v)==8+count*stride
        vertex=[];classification=[]
        for i in range(count):
            raw=v[8+i*stride:8+(i+1)*stride]
            if stride==60:bones=[struct.unpack_from('<I',raw,56)[0]];weights=[1.];start=0;uv=48
            elif stride==64:bones=struct.unpack_from('<2H',raw);w=struct.unpack_from('<f',raw,52)[0];weights=[1-w,w];start=4;uv=56
            elif stride==70:bones=struct.unpack_from('<3H',raw);w1,w2=struct.unpack_from('<2f',raw,54);weights=[w1,w2,1-w1-w2];start=6;uv=62
            else:bones=struct.unpack_from('<4H',raw);w=struct.unpack_from('<3f',raw,56);weights=[*w,1-sum(w)];start=8;uv=68
            assert all(0<=b<n for b in bones) and all(math.isfinite(w) for w in weights)
            combined=collections.Counter()
            for b,w in zip(bones,weights):combined[b]+=w
            dominant=max(combined,key=combined.get)
            classification.append(classify(names[dominant],parents))
            # Exactly the original 14 floats, followed by a rigid root index.
            output=raw[start:start+48]+raw[uv:uv+8]+struct.pack('<I',0)
            assert len(output)==60 and all(math.isfinite(f) for f in struct.unpack('<14f',output[:56]))
            vertex.append(output)
        count,=struct.unpack_from('<I',mesh[4]);ids=struct.unpack_from('<'+str(count)+'H',mesh[4],4)
        assert count%3==0
        for i in range(0,count,3):
            triangle=ids[i:i+3];votes=collections.Counter(classification[v] for v in triangle)
            groups[votes.most_common(1)[0][0]][mesh[2]].append(tuple(vertex[v] for v in triangle));total+=1
    assert 'body' in groups and 1<=len(groups)<=20
    mass=sum(p['mass'] for p in old[relative]['parts'])
    weights={name:.04 if 'wheel' in name else .025 for name in groups if name!='body'}
    weights['body']=max(.4,1-sum(weights.values()));norm=sum(weights.values())
    template=chunks((a.template_candidate/'meshes'/old[relative]['parts'][0]['path']).read_bytes())[16]
    assert struct.unpack_from('<6f',template,len(template)-40)==(0.,)*6
    parts=[]
    for name,materials in groups.items():
        children={};points=[];triangles=0
        for material,faces in materials.items():
            for first in range(0,len(faces),12000):
                used={};vertices=[];indices=[]
                for face in faces[first:first+12000]:
                    for v in face:
                        if v not in used:used[v]=len(vertices);vertices.append(v)
                        indices.append(used[v])
                coords=[struct.unpack_from('<3f',v) for v in vertices];points+=coords
                sub={1:header(5,coords),2:material,3:struct.pack('<II',1,len(vertices))+b''.join(vertices),4:struct.pack('<I',len(indices))+struct.pack('<'+'H'*len(indices),*indices)}
                children[len(children)]=packed(sub);triangles+=len(indices)//3
        lo,hi,centre,half,_=bounds(points)
        identity=(1,0,0,0,1,0,0,0,1)
        bone=struct.pack('<I',1)+b'root\0\0'+struct.pack('<15f',*identity,*centre,*half)
        ik=bytearray(template);end=ik.index(0,4)+1
        struct.pack_into('<HH',ik,end,1,0);struct.pack_into('<15f',ik,end+4,*identity,*centre,*half)
        part_mass=mass*weights[name]/norm;struct.pack_into('<4f',ik,len(ik)-16,part_mass,*centre)
        userdata=b'[impulse_transition_from_source_bone]\nref_bone = root\nimp_transition_factor = 0.1\nlv_transition_factor = 1\nav_transition_factor = 1\n\0'
        output=packed({1:header(10,points),9:packed(children),13:bone,16:bytes(ik),17:userdata})
        path=Path('physics/vehicles/lz_debris')/Path(relative).stem/(name+'.ogf')
        target=a.out/'meshes'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(output)
        # Report bounds remain in Blender XYZ for compatibility with old reports.
        parts.append(dict(name=name,path=path.as_posix(),triangles=triangles,mass=part_mass,lo=[lo[0],lo[2],lo[1]],hi=[hi[0],hi[2],hi[1]],sha256=sha(output)))
    assert sum(p['triangles'] for p in parts)==total
    report.append(dict(source=relative,source_sha256=sha(data),triangles=total,parts=parts,rigid_only=len(parts)==1))
    print('Binary split',relative,len(parts),'parts',total,'triangles',flush=True)
    (a.out/'debris-reviewed-candidate.json').write_text(json.dumps(report,indent=2)+'\n')

"""Review generated OGF fragments against actual donor geometry, offline only."""
import argparse, collections, hashlib, json, math, struct
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('candidate',type=Path)
p.add_argument('--only',default='')
a=p.parse_args();root=Path(__file__).resolve().parents[1]

def chunks(data):
    result={};offset=0
    while offset<len(data):
        tag,size=struct.unpack_from('<II',data,offset);offset+=8
        assert not tag&0x80000000 and offset+size<=len(data)
        assert tag not in result
        result[tag]=data[offset:offset+size];offset+=size
    assert offset==len(data)
    return result

def geometry(data):
    result=collections.Counter();c=chunks(data)
    if 9 in c:
        for child in chunks(c[9]).values():result.update(geometry(child))
        return result
    vertices=c[3];kind,count=struct.unpack_from('<II',vertices)
    # Current DCP source and rigid exported parts use one/two-link OGF4.
    stride=(len(vertices)-8)//count
    assert stride in {36,60,64,70,76} and len(vertices)==8+count*stride,(kind,stride)
    offset={36:0,60:0,64:4,70:6,76:8}[stride]
    uv_offset={36:24,60:48,64:56,70:62,76:68}[stride]
    decoded=[]
    for i in range(count):
        point=struct.unpack_from('<3f',vertices,8+i*stride+offset)
        uv=struct.unpack_from('<2f',vertices,8+i*stride+uv_offset)
        assert all(math.isfinite(v) for v in (*point,*uv))
        decoded.append(tuple(round(v,4) for v in point)+tuple(round(v,5) for v in uv))
    n,=struct.unpack_from('<I',c[4]);assert n%3==0 and len(c[4])==4+n*2
    indices=struct.unpack_from('<'+str(n)+'H',c[4],4);assert max(indices)<count
    texture=c[2].split(b'\0',1)[0].lower().replace(b'\\',b'/')
    for i in range(0,n,3):result[(texture,tuple(sorted(decoded[v] for v in indices[i:i+3])))]+=1
    return result

rows=json.loads((a.candidate/'debris-reviewed-candidate.json').read_text());reviewed=[]
for row in rows:
    if a.only and a.only not in row['source']:continue
    source=root/'scripts/netcoop-overlay/client/meshes'/row['source']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==row['source_sha256']
    original=geometry(source.read_bytes());parts=collections.Counter()
    for part in row['parts']:
        data=(a.candidate/'meshes'/part['path']).read_bytes();c=chunks(data)
        assert hashlib.sha256(data).hexdigest()==part['sha256']
        assert struct.unpack_from('<I',c[13])[0]==1
        assert c[13][4:].startswith(b'root\0\0')
        g=geometry(data);assert sum(g.values())==part['triangles'];parts.update(g)
        ik=c[16];end=ik.index(0,4)+1
        shape,flags=struct.unpack_from('<HH',ik,end)
        assert shape==1 and not flags&4
        shape_data=struct.unpack_from('<27f',ik,end+4)
        assert all(math.isfinite(v) for v in shape_data) and min(shape_data[12:15])>=.0149
        mass=struct.unpack_from('<f',ik,len(ik)-16)[0]
        assert abs(mass-part['mass'])<.01 and mass>0
        assert b'ref_bone = ' in c[17]
    assert parts==original,(row['source'],'geometry / UV changed',sum((original-parts).values()),sum((parts-original).values()))
    reviewed.append(row['source']);print('Reviewed',row['source'],len(row['parts']),'pieces',flush=True)
assert reviewed
out={'vehicles':len(reviewed),'parts':sum(len(r['parts']) for r in rows if r['source'] in reviewed),
     'source_geometry_uv_materials_preserved':True,'positive_mass_box_colliders':True,'native_game_launched':False}
if not a.only:
    assert len(reviewed)==50
    (a.candidate/'binary-reviewed.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out))

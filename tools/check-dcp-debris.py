"""Review generated OGF fragments against actual donor geometry, offline only."""
import argparse, collections, hashlib, json, math, struct
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('candidate',type=Path)
p.add_argument('--only',default='')
p.add_argument('--exact-attributes',action='store_true')
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

def geometry(data,degenerate=None):
    result=collections.Counter();c=chunks(data)
    if 9 in c:
        for child in chunks(c[9]).values():result.update(geometry(child,degenerate))
        return result
    vertices=c[3];kind,count=struct.unpack_from('<II',vertices)
    # Current DCP source and rigid exported parts use one/two-link OGF4.
    stride=(len(vertices)-8)//count
    assert stride in {36,60,64,70,76} and len(vertices)==8+count*stride,(kind,stride)
    offset={36:0,60:0,64:4,70:6,76:8}[stride]
    uv_offset={36:24,60:48,64:56,70:62,76:68}[stride]
    decoded=[];positions=[]
    for i in range(count):
        point=struct.unpack_from('<3f',vertices,8+i*stride+offset)
        uv=struct.unpack_from('<2f',vertices,8+i*stride+uv_offset)
        assert all(math.isfinite(v) for v in (*point,*uv))
        positions.append(point)
        if a.exact_attributes:
            begin=8+i*stride
            decoded.append(vertices[begin+offset:begin+offset+48]+vertices[begin+uv_offset:begin+uv_offset+8])
        else:decoded.append(tuple(round(v,4) for v in point)+tuple(round(v,5) for v in uv))
    n,=struct.unpack_from('<I',c[4]);assert n%3==0 and len(c[4])==4+n*2
    indices=struct.unpack_from('<'+str(n)+'H',c[4],4);assert max(indices)<count
    # Include the shader too; matching the texture alone misses opaque glass.
    texture=c[2] if a.exact_attributes else c[2].lower().replace(b'\\',b'/')
    for i in range(0,n,3):
        ids=indices[i:i+3];triangle=tuple(decoded[v] for v in ids)
        # Cyclic order preserves face orientation; reversing the winding is a
        # visible surface change and must not be hidden by sorting vertices.
        key=(texture,min(triangle,triangle[1:]+triangle[:1],triangle[2:]+triangle[:2]))
        result[key]+=1
        if degenerate is not None:
            p0,p1,p2=(positions[v] for v in ids)
            u=tuple(p1[k]-p0[k] for k in range(3));v=tuple(p2[k]-p0[k] for k in range(3))
            if all(u[(k+1)%3]*v[(k+2)%3]-u[(k+2)%3]*v[(k+1)%3]==0 for k in range(3)):degenerate.add(key)
    return result

rows=json.loads((a.candidate/'debris-reviewed-candidate.json').read_text());reviewed=[]
for row in rows:
    if a.only and a.only not in row['source']:continue
    source=root/'scripts/netcoop-overlay/client/meshes'/row['source']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==row['source_sha256']
    degenerate=set();original=geometry(source.read_bytes(),degenerate);parts=collections.Counter()
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
    missing=original-parts;added=parts-original
    # The donor importer removes triangles with exactly zero area. They have
    # no rendered surface. Every nondegenerate face, winding, UV and material
    # must survive; added or changed triangles still fail this check.
    assert not added and set(missing)<=degenerate,(row['source'],'surface / UV changed',sum(missing.values()),sum(added.values()))
    reviewed.append(row['source']);print('Reviewed',row['source'],len(row['parts']),'pieces',flush=True)
assert reviewed
out={'vehicles':len(reviewed),'parts':sum(len(r['parts']) for r in rows if r['source'] in reviewed),
     'source_geometry_uv_materials_preserved':True,'source_normals_tangents_shader_bytes_exact':a.exact_attributes,
     'positive_mass_box_colliders':True,'native_game_launched':False}
if not a.only:
    assert len(reviewed)==50
    (a.candidate/'binary-reviewed.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out))

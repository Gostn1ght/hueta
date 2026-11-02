// Included at the end of Actor.cpp. No seat, attachment or fixed player joint.
namespace netcoop
{
struct PlatformFrame { u32 time; Fmatrix pose; };
struct PlatformHistory { CCar* object=nullptr; xr_deque<PlatformFrame> frames; };
static xr_map<u16,PlatformHistory> s_platform_history;
void platform_record(CCar* car)
{
 if(!car || pure_client()) return;
 auto& history=s_platform_history[car->ID()];
 if(history.object!=car) {history.frames.clear();history.object=car;}
 const u32 now=Level().timeServer();
 if(!history.frames.empty() && history.frames.back().time==now) return;
 history.frames.push_back({now,car->XFORM()});
 while(history.frames.size()>32 || (!history.frames.empty() && now-history.frames.front().time>1200)) history.frames.pop_front();
 if(s_platform_history.size()>512)
  for(auto it=s_platform_history.begin();it!=s_platform_history.end();)
   if(Level().Objects.net_Find(it->first)!=it->second.object) it=s_platform_history.erase(it);else ++it;
}

// Three nearby contacts reject a side, roof edge or steep panel. The returned
// surface is the actual car collider, not its visual bounding box.
static CCar* platform_surface(CActor* actor,const Fvector& feet,CCar* required=nullptr)
{
 Fvector hit_points[3];CCar* car=nullptr;
 for(u32 i=0;i<3;++i) {
  Fvector start=feet,down;start.y+=.3f;down.set(0,-1,0);
  if(i==1) start.x+=.12f;if(i==2) start.z+=.12f;
  collide::rq_result hit;
  if(!Level().ObjectSpace.RayPick(start,down,.65f,collide::rqtObject,hit,actor)) return nullptr;
  CCar* found=smart_cast<CCar*>(hit.O);
  if(!found || found->getDestroy() || found->netcoop_destroyed() || found->netcoop_is_heli() ||
   (required && found!=required) || (car && found!=car)) return nullptr;
  car=found;hit_points[i].mad(start,down,hit.range);
 }
 Fvector a,b,normal;a.sub(hit_points[2],hit_points[0]);b.sub(hit_points[1],hit_points[0]);normal.crossproduct(a,b);
 if(normal.square_magnitude()<EPS_S) return nullptr;
 normal.normalize();if(_abs(normal.y)<.75f) return nullptr;
 const float gap=feet.y-hit_points[0].y;
 return gap>=-.10f && gap<=.23f ? car:nullptr;
}
}

void CActor::netcoop_platform_detach(bool inherit_velocity)
{
 if(m_netcoop_platform_car==0xffff) return;
 if(inherit_velocity && netcoop::pure_client() && this==Level().CurrentControlEntity()) {
  auto* control=character_physics_support() ? character_physics_support()->movement():nullptr;
  if(control && control->CharacterExist()) {
   Fvector velocity=control->GetVelocity();velocity.add(m_netcoop_platform_velocity);
   if(_valid(velocity) && velocity.magnitude()<100.f) control->SetVelocity(velocity);
  }
 }
 Msg("[diag][platform] actor=%u left car=%u inherited=%u",ID(),m_netcoop_platform_car,inherit_velocity?1:0);
 if(!netcoop::pure_client()) {
  m_netcoop_platform_departure=m_netcoop_platform_velocity;
  m_netcoop_platform_departure_time=Level().timeServer();
  m_netcoop_platform_departure_until=m_netcoop_platform_departure_time+2000;
 }
 m_netcoop_platform_car=0xffff;m_netcoop_platform_object=nullptr;m_netcoop_platform_time=0;
 m_netcoop_platform_velocity.set(0,0,0);
}

void CActor::netcoop_platform_update()
{
 if(!netcoop::pure_client() || this!=Level().CurrentControlEntity() || m_netcoop_platform_frame==Device.dwFrame) return;
 m_netcoop_platform_frame=Device.dwFrame;
 if(!g_Alive() || netcoop_seated() || m_netcoop_noclip || getDestroy()) {netcoop_platform_detach(false);return;}
 if(mstate_wishful & (mcJump|mcClimb)) {netcoop_platform_detach(true);return;}
 auto* control=character_physics_support() ? character_physics_support()->movement():nullptr;
 if(!control || !control->CharacterExist()) {netcoop_platform_detach(false);return;}
 if(m_netcoop_platform_car==0xffff && control->GetVelocity().y>.5f) return;
 Fvector candidate=Position();
 CCar* car=smart_cast<CCar*>(Level().Objects.net_Find(m_netcoop_platform_car));
 if(car && car==m_netcoop_platform_object && !car->getDestroy()) {
  car->netcoop_physics_follow();
  Fmatrix inverse;inverse.invert(m_netcoop_platform_pose);
  Fvector relative;inverse.transform_tiny(relative,candidate);car->XFORM().transform_tiny(candidate,relative);
  Fvector shift;shift.sub(candidate,Position());
  const float elapsed=_max(.001f,float(Device.dwTimeGlobal-m_netcoop_platform_time)/1000.f);
  if(!_valid(candidate) || elapsed>.5f || shift.magnitude()>80.f*elapsed+.15f) {netcoop_platform_detach(false);return;}
  m_netcoop_platform_velocity.mul(shift,1.f/elapsed);
  if(shift.square_magnitude()>EPS_S) {
   Fvector start=Position(),direction=shift;start.y+=.6f;direction.normalize();collide::rq_result wall;
   if(Level().ObjectSpace.RayPick(start,direction,shift.magnitude(),collide::rqtStatic,wall,this)) {netcoop_platform_detach(true);return;}
  }
  control->SetPosition(candidate);Position().set(candidate);
  Fvector before,after;m_netcoop_platform_pose.getXYZi(before);car->XFORM().getXYZi(after);
  const float yaw=angle_difference_signed(after.y,before.y);
  for(int i=0;i<eacMaxCam;++i) if(cameras[i]) cameras[i]->yaw+=yaw;
  r_model_yaw+=yaw;r_model_yaw_dest+=yaw;r_torso.yaw+=yaw;unaffected_r_torso.yaw+=yaw;
 }
 CCar* support=netcoop::platform_surface(this,Position());
 if(!support) {netcoop_platform_detach(true);return;}
 if(support!=m_netcoop_platform_object) {
  netcoop_platform_detach(false);m_netcoop_platform_velocity.set(0,0,0);
  Msg("[diag][platform] actor=%u standing on car=%u",ID(),support->ID());
 }
 m_netcoop_platform_car=support->ID();m_netcoop_platform_object=support;
 m_netcoop_platform_pose.set(support->XFORM());m_netcoop_platform_time=Device.dwTimeGlobal;
 Fmatrix inverse;inverse.invert(support->XFORM());inverse.transform_tiny(m_netcoop_platform_local,Position());
 spatial_move();
}

bool CActor::netcoop_platform_accept(u16 id,const Fvector& local,Fvector reported,Fvector& target,Fvector& base)
{
 CCar* car=smart_cast<CCar*>(Level().Objects.net_Find(id));
 if(!car || !_valid(local) || !_valid(reported) || car->getDestroy() || netcoop_seated() || m_netcoop_noclip) return false;
 auto found=netcoop::s_platform_history.find(id);
 if(found==netcoop::s_platform_history.end() || found->second.object!=car) return false;
 const netcoop::PlatformFrame* match=nullptr;float nearest=1.25f*1.25f;
 for(const auto& frame:found->second.frames) {
  Fvector expected;frame.pose.transform_tiny(expected,local);
  const float distance=expected.distance_to_sqr(reported);
  if(distance<nearest) {nearest=distance;match=&frame;}
 }
 if(!match) return false;
 car->XFORM().transform_tiny(target,local);
 if(netcoop::platform_surface(this,target,car)!=car) return false;
 Fvector previous;
 if(m_netcoop_platform_car==id && m_netcoop_platform_object==car) previous=m_netcoop_platform_local;
 else {
  // Initial boarding must originate beside the same historical surface.
  if(Position().distance_to(reported)>2.5f) return false;
  Fmatrix inverse;inverse.invert(match->pose);inverse.transform_tiny(previous,Position());
 }
 car->XFORM().transform_tiny(base,previous);
 const auto& frames=found->second.frames;
 if(frames.size()>=2) {
  const auto& a=frames[frames.size()-2];const auto& b=frames.back();
  Fvector pa,pb;a.pose.transform_tiny(pa,local);b.pose.transform_tiny(pb,local);
  m_netcoop_platform_velocity.sub(pb,pa).mul(1000.f/_max(1u,b.time-a.time));
  if(!_valid(m_netcoop_platform_velocity) || m_netcoop_platform_velocity.magnitude()>80.f)
   m_netcoop_platform_velocity.set(0,0,0);
 }
 m_netcoop_platform_departure_until=0;
 m_netcoop_platform_car=id;m_netcoop_platform_object=car;
 m_netcoop_platform_pose.set(car->XFORM());m_netcoop_platform_time=Level().timeServer();
 // The ordinary owner movement budget below still bounds walking in this frame.
 return true;
}

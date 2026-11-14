function CGeneralTask:save_state(m_data)
	--utils_data.debug_write(strformat("CGeneralTask:save_state %s BEFORE",self.id))
	if (self.t == nil) then
		if (self.repeat_timeout == nil or self.timeout == nil) then 
			return 
		end
		if (game.get_game_time():diffSec(self.timeout) > self.repeat_timeout) then 
			return
		end
	end 
	
	m_data.task_objects[self.id] = {}
	m_data.task_objects[self.id].status = self.status
	m_data.task_objects[self.id].timeout = self.timeout
	m_data.task_objects[self.id].inited_time = self.inited_time
	m_data.task_objects[self.id].current_title = self.current_title
	m_data.task_objects[self.id].current_descr = self.current_descr
	m_data.task_objects[self.id].current_target = self.current_target
	m_data.task_objects[self.id].stage = self.stage
	m_data.task_objects[self.id].task_giver_id = self.task_giver_id
	--utils_data.debug_write(strformat("CGeneralTask:save_state %s AFTER",self.id))
end 

function CGeneralTask:load_state(m_data)
	if not (m_data.task_objects and m_data.task_objects[self.id]) then 
		return false
	end 
	--utils_data.debug_write(strformat("CGeneralTask:load_state %s BEFORE",self.id))
	self.status = m_data.task_objects[self.id].status
	self.timeout = m_data.task_objects[self.id].timeout
	self.inited_time = m_data.task_objects[self.id].inited_time
	self.current_title = m_data.task_objects[self.id].current_title
	self.current_descr = m_data.task_objects[self.id].current_descr
	self.current_target = m_data.task_objects[self.id].current_target
	self.stage = m_data.task_objects[self.id].stage
	self.task_giver_id =  m_data.task_objects[self.id].task_giver_id
	m_data.task_objects[self.id] = nil
	
	self.loaded = true
	
	--utils_data.debug_write(strformat("CGeneralTask:load_state %s AFTER",self.id))
	return true
end 
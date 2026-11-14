function save_state(m_data)
	--utils_data.debug_write("task_manager.save_state")
	m_data.task_info = not m_data.task_info and {} or empty_table(m_data.task_info)
	m_data.task_objects = not m_data.task_objects and {} or empty_table(m_data.task_objects)
	
	local tm = get_task_manager()
	
	for k,v in pairs(tm.task_info) do
		m_data.task_info[k] = true
		tm.task_info[k]:save_state(m_data)
	end
end 

function load_state(m_data)
	if not (m_data.task_info) then 
		return 
	end 
	
	local tm = get_task_manager()
	
	for task_id,v in pairs(m_data.task_info) do 
		local obj = task_objects.CGeneralTask(task_id)
		if (obj:load_state(m_data) == true) then
			tm.task_info[task_id] = obj
			--[[
			local t = db.actor and db.actor:get_task(obj.id,true)
			if (t) then
				t:add_complete_func("task_manager.task_complete")
				t:add_fail_func("task_manager.task_fail")
			end
			--]]
		end
	end
	
	m_data.task_info = nil
end
function CRandomTask:task_complete(p1)
	if (db.actor == nil or device().precache_frame > 1) then 
		return false 
	end 
	
	local tsk = self.task_info[p1]
	if tsk == nil then
		printe("!ERROR: CRandomTask:task_complete %s task is nil!",p1)
		return true
	end
	
	if (tsk.forced_status == "complete") then
		tsk.forced_status = nil
		tsk.last_check_task = "complete"
	elseif (tsk.forced_status == "fail") then 
		return false
	end
	
	if tsk.last_check_task == "complete" then
		return true
	end
	return false
end
--' Проверяем, не профейлен ли таск

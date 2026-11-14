function CRandomTask:update()
	--utils_data.debug_write("CRandomTask:update() - START")
	for k,v in pairs(self.task_info) do
		local tsk = self.task_info[k]
		tsk:check_task()
		if (tsk.timeout and game.get_game_time():diffSec(tsk.timeout) > tsk.repeat_timeout) then
			if (ui_options.get("alife/dynamic_news/nearby_activity_news")) then
				dynamic_news_manager.get_dynamic_news():GossipTaskRepeatTimeout(k)
			end
			if not (db.actor:get_task(k,true)) then -- don't remove if engine task object still exist
				self.task_info[k] = nil
			end
		end
	end
	--utils_data.debug_write("CRandomTask:update() - END")
end 

--' Проверяем, не выполнен ли таск

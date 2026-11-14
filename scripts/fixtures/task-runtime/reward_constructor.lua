function CGeneralTask:__init(id)
 self.id=id
 self.on_complete=task_manager.task_ini:r_string_to_condlist(id,"on_complete")
 local task_ini=task_manager.task_ini
	self.reward_money = task_ini:r_string_to_condlist(id,"reward_money")
	self.reward_item = task_ini:r_string_to_condlist(id,"reward_money")
end

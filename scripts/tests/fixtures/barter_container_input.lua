-- Actual base utils_ui.script input methods; SHA256 d407f040874d9a697f53dc4d9e59558662694d6cf99ca71d87ae19685e8a5c2e
UICellContainer = {}
function UICellContainer:On_Drag(idx, tg, set)

	-- Hold icon should be declared after everything else, so it stays on top
	-- Also it must be assigned on the base UI because we need x and y to start from absolute screen corner
	if (not self.hold.ico) then
		self.hold.ico = self.xml:InitStatic(self.path .. ":cell:pic", self.owner) 
		self.hold.ico:Show(false)
	end
	
	if (self.disable_drag) then
		return
	end
	
	-- Drag start / Drop
	if set then
		self:Print(nil, "Drag | hold_idx: %s - hold_tg: %s", idx, tg)
		
		-- Callback
		if (not idx) and self.hold.idx and (self.hold.idx ~= self.hover.idx) then -- IF released mouse + drag item is captured + drag item is not hovered item
			self:Callback( "On_CC_DragDrop", self.ID, self.hold.idx )
		end
		
		-- Useful to prevent some actions for owner when there's a dragged item, by checking on (self.item_in_hold)
		if self.owner.item_in_hold == self.ID then
			self.owner.item_in_hold = false
		end
		if idx then
			self.owner.item_in_hold = self.ID
			
			-- Hold the scroll and stop moving on dragging
			self.scroll_pos = self.scroll:GetCurrentScrollPos()
			
			-- No point of holding empty cells
			if (not self.cell[idx]:IsShown()) then
				return
			end
		end
		
		self.hold.idx = idx
		self.hold.tg = tg
		self.hold.ico:Show(false)
		return
	end
	
	-- Drag
	if self.hold.idx and tg - self.hold.tg > 100 then
		
		-- Set up drag item icon
		if (not self.hold.ico:IsShown()) then
			self:Print(nil, "Drag | set up icon")
			local sec = self.cell[self.hold.idx].section
			
			if sec then
				self.hold.w = SYS_GetParam(2,sec, "inv_grid_width") * self.grid_size * ratio
				self.hold.h = SYS_GetParam(2,sec, "inv_grid_height") * self.grid_size
				
				self.hold.ico:InitTexture( utils_xml.get_icons_texture(sec) )
				self.hold.ico:SetTextureRect(Frect():set( get_item_axis(sec, nil, true) ))
				self.hold.ico:SetTextureColor( clr_list["drag"] )
				self.hold.ico:SetStretchTexture(true)
				self.hold.ico:SetWndSize(vector2():set(self.hold.w , self.hold.h))
				self.hold.ico:Show(true)
			end
		end
		
		-- Sync with cursor pos
		local pos = GetCursorPosition()
		self.hold.ico:SetWndPos( pos )
	end
end
function UICellContainer:On_Mouse1(idx)

	-- Anticipate double click
	local tg = get_time()
	
	if (tg - self.db.tg < 400) then
		self.db.idx = idx --false
		self.db.tg = tg
		
		local db_continue = self:On_Mouse1_DB(idx)
		
		-- when there's a value returned, allow consecutive db clicks
		if (not db_continue) then
			self.db.idx = false
		end
		
		-- db_continue is false if no db callback is found in owner class, so we can pass the return and treat db click as normal click 
		if (db_continue ~= false) then
			return
		end
	end
	
	self.db.idx = idx
	self.db.tg = tg
	self:On_Select(idx)

	self:Callback( "On_CC_Mouse1", self.ID, idx )
end
function UICellContainer:On_Mouse1_DB(idx)
	return self:Callback( "On_CC_Mouse1_DB", self.ID, idx ) -- Returning true means no cooldown on double clicking if you keep clicking!
end
function UICellContainer:OnKeyboard(dik, keyboard_action)
	
	-- Pause scrolling when holding M1
	if (dik == K_M1) then
		if (keyboard_action == E_PRESS) then
			self.scroll_pause = true
		elseif (keyboard_action == E_RELEASE) then
			self.scroll_pause = false
		end
	end
	
	-- Interaction with cells
	local idx = self.hover.idx
	if idx then

		-- Mouse 1
		if (dik == K_M1) then
			if (keyboard_action == E_PRESS) then
				self:On_Drag(idx, get_time(), true)
				
			elseif (keyboard_action == E_RELEASE) then
				self:On_Drag(false, 0, true)
				self:On_Mouse1(idx)
			end
		
		-- Mouse 2
		elseif (dik == K_M2) then
			if (keyboard_action == E_RELEASE) then
				self:On_Mouse2(idx)
			end
		end

	-- We disable drag on releasing regardless of highlighted cell
	elseif (dik == K_M1) and (keyboard_action == E_RELEASE) then
		self:On_Drag(false, 0, true)
	end
	
	-- Left shift
	if (dik == K_SHFT) then
		self.scolling_power = (keyboard_action == E_PRESS) and self.scolling_power_up or 1
	end
end
function UICellContainer:Callback(func, ...)
	-- This is needed for inventory UI to avoid endless loop for slots managements
	if self.disable_callback[func] then
		return
	end
	
	if self.owner[func] then
		return self.owner[func](self.owner,...)
		
	elseif (func == "On_CC_Mouse1_DB") then
		return false
	end
end

// Runs after VFS mount, before settings/Lua. The updater removes its obsolete
// managed configs but intentionally retains axr_options and unknown user files.
#pragma once
static bool client_config_digest(LPCSTR path,u64& size,u64& hash)
{
    FILE* in=fopen(path,"rb");if(!in) return false;size=0;hash=14695981039346656037ULL;
    unsigned char bytes[16384];size_t got=0;
    while((got=fread(bytes,1,sizeof(bytes),in))!=0) {size+=got;for(size_t i=0;i<got;++i) {hash^=bytes[i];hash*=1099511628211ULL;}}
    const bool ok=!ferror(in);fclose(in);return ok;
}
static bool client_config_parent(LPCSTR path)
{
    string_path directory;xr_strcpy(directory,path);
    for(char* c=directory+3;*c;++c) if(*c=='\\') {*c=0;const bool ok=CreateDirectoryA(directory,nullptr) || GetLastError()==ERROR_ALREADY_EXISTS;*c='\\';if(!ok) return false;}
    return true;
}
static bool client_config_copy_tree(LPCSTR old_root,LPCSTR relative,CInifile& baseline,u32& copied)
{
    string_path mask;xr_sprintf(mask,"%s%s*",old_root,relative);
    WIN32_FIND_DATAA found;HANDLE scan=FindFirstFileA(mask,&found);if(scan==INVALID_HANDLE_VALUE) return true;
    bool ok=true;
    do {
        if(!xr_strcmp(found.cFileName,".") || !xr_strcmp(found.cFileName,"..")) continue;
        if(xr_strlen(old_root)+xr_strlen(relative)+xr_strlen(found.cFileName)+3>=sizeof(string_path)) {ok=false;continue;}
        if(found.dwFileAttributes&FILE_ATTRIBUTE_REPARSE_POINT) {ok=false;continue;}
        string_path rel,path;xr_sprintf(rel,"%s%s",relative,found.cFileName);xr_sprintf(path,"%s%s",old_root,rel);
        if(found.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY) {
            xr_strcat(rel,"\\");if(!client_config_copy_tree(old_root,rel,baseline,copied)) ok=false;continue;
        }
        u64 size=0,hash=0;if(!client_config_digest(path,size,hash)) {ok=false;continue;}
        if(baseline.line_exist("old_configs",rel)) {
            unsigned long long expected_size=0,expected_hash=0;
            if(sscanf(baseline.r_string("old_configs",rel),"%llu,%llx",&expected_size,&expected_hash)==2 && size==expected_size && hash==expected_hash) continue;
        }
        string_path target;FS.update_path(target,"$game_config$",rel);
        // A newer appdata override always wins over the old physical folder.
        if(GetFileAttributesA(target)!=INVALID_FILE_ATTRIBUTES) continue;
        if(!client_config_parent(target) || !CopyFileA(path,target,TRUE)) {ok=false;continue;}
        ++copied;
    }while(FindNextFileA(scan,&found));
    FindClose(scan);return ok;
}
static void migrate_client_configs()
{
    if(g_dedicated_server) return;
    string_path marker;
    if(!FS.exist(marker,"$game_config$","netcoop\\config_migration_000047.ltx")) return;
    string_path source,old_configs,config_root;
    FS.update_path(source,"$fs_root$","client");
    const DWORD source_attributes=GetFileAttributesA(source);
    if(source_attributes==INVALID_FILE_ATTRIBUTES || (source_attributes&FILE_ATTRIBUTE_REPARSE_POINT)) return;
    FS.update_path(old_configs,"$fs_root$","client\\configs\\");FS.update_path(config_root,"$game_config$","");
    if(!_strnicmp(config_root,source,xr_strlen(source))) return; // legacy template still active
    CInifile baseline(marker,TRUE,TRUE,FALSE);u32 copied=0;
    if(!client_config_copy_tree(old_configs,"",baseline,copied)) {
        Msg("! [diag][migration] legacy client config migration incomplete; source retained; copied=%u",copied);return;
    }
    string_path backup,relative;
    xr_sprintf(relative,"migration\\legacy-client-000047-%u-%llu",GetCurrentProcessId(),GetTickCount64());
    FS.update_path(backup,"$app_data_root$",relative);
    if(!client_config_parent(backup) || !MoveFileExA(source,backup,MOVEFILE_WRITE_THROUGH)) {
        Msg("! [diag][migration] client folder could not be archived Win32=%u; original retained",GetLastError());return;
    }
    FS.rescan_path(config_root,TRUE);
    Msg("[diag][migration] client folder archived under appdata; preserved %u changed/custom configs; unchanged defaults now use archives",copied);
}

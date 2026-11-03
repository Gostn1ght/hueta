//! Системные мелочи Windows: DPAPI, ярлыки, реестр, время, самоудаление.

use anyhow::{anyhow, Result};
use std::io::Write;
use std::path::{Path, PathBuf};

/// Шифрование строки ключом текущего пользователя Windows (DPAPI).
pub fn protect(s: &str) -> String {
    use base64::Engine;
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{CryptProtectData, CRYPT_INTEGER_BLOB};
    if s.is_empty() {
        return String::new();
    }
    let inp = CRYPT_INTEGER_BLOB { cbData: s.len() as u32, pbData: s.as_ptr() as *mut u8 };
    let mut out = CRYPT_INTEGER_BLOB { cbData: 0, pbData: std::ptr::null_mut() };
    let ok = unsafe { CryptProtectData(&inp, std::ptr::null(), std::ptr::null(), std::ptr::null(), std::ptr::null(), 0, &mut out) };
    if ok == 0 {
        return String::new();
    }
    let v = unsafe { std::slice::from_raw_parts(out.pbData, out.cbData as usize).to_vec() };
    unsafe { LocalFree(out.pbData as _) };
    base64::engine::general_purpose::STANDARD.encode(v)
}

pub fn unprotect(s: &str) -> String {
    use base64::Engine;
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{CryptUnprotectData, CRYPT_INTEGER_BLOB};
    let Ok(data) = base64::engine::general_purpose::STANDARD.decode(s) else { return String::new() };
    if data.is_empty() {
        return String::new();
    }
    let inp = CRYPT_INTEGER_BLOB { cbData: data.len() as u32, pbData: data.as_ptr() as *mut u8 };
    let mut out = CRYPT_INTEGER_BLOB { cbData: 0, pbData: std::ptr::null_mut() };
    let ok = unsafe {
        CryptUnprotectData(&inp, std::ptr::null_mut(), std::ptr::null(), std::ptr::null(), std::ptr::null(), 0, &mut out)
    };
    if ok == 0 {
        return String::new();
    }
    let v = unsafe { std::slice::from_raw_parts(out.pbData, out.cbData as usize).to_vec() };
    unsafe { LocalFree(out.pbData as _) };
    String::from_utf8(v).unwrap_or_default()
}

/// Строка в ANSI-кодовой странице Windows (у русской Windows — 1251), как `-Encoding Default`.
pub fn to_ansi(s: &str) -> Vec<u8> {
    use windows_sys::Win32::Globalization::{WideCharToMultiByte, CP_ACP};
    let w: Vec<u16> = s.encode_utf16().collect();
    if w.is_empty() {
        return Vec::new();
    }
    unsafe {
        let n = WideCharToMultiByte(CP_ACP, 0, w.as_ptr(), w.len() as i32, std::ptr::null_mut(), 0, std::ptr::null(), std::ptr::null_mut());
        let mut out = vec![0u8; n.max(0) as usize];
        WideCharToMultiByte(CP_ACP, 0, w.as_ptr(), w.len() as i32, out.as_mut_ptr(), n, std::ptr::null(), std::ptr::null_mut());
        out
    }
}

pub fn local_time() -> String {
    use windows_sys::Win32::System::SystemInformation::GetLocalTime;
    let mut t = unsafe { std::mem::zeroed() };
    unsafe { GetLocalTime(&mut t) };
    format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02}", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond)
}

/// Ярлык через IShellLinkW — корректно работает с кириллицей в путях.
pub fn create_shortcut(lnk: &Path, target: &Path, args: &str, workdir: &Path, desc: &str) -> Result<()> {
    let (lnk, target, args, workdir, desc) = (lnk.to_path_buf(), target.to_path_buf(), args.to_string(), workdir.to_path_buf(), desc.to_string());
    std::thread::spawn(move || -> Result<()> {
        use windows::core::{Interface, HSTRING};
        use windows::Win32::System::Com::{CoCreateInstance, CoInitializeEx, IPersistFile, CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED};
        use windows::Win32::UI::Shell::{IShellLinkW, ShellLink};
        if let Some(p) = lnk.parent() {
            std::fs::create_dir_all(p)?;
        }
        unsafe {
            let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
            let link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER)?;
            link.SetPath(&HSTRING::from(target.as_os_str()))?;
            link.SetArguments(&HSTRING::from(args.as_str()))?;
            link.SetWorkingDirectory(&HSTRING::from(workdir.as_os_str()))?;
            link.SetIconLocation(&HSTRING::from(target.as_os_str()), 0)?;
            link.SetDescription(&HSTRING::from(desc.as_str()))?;
            let pf: IPersistFile = link.cast()?;
            pf.Save(&HSTRING::from(lnk.as_os_str()), true)?;
        }
        Ok(())
    })
    .join()
    .map_err(|_| anyhow!("ошибка создания ярлыка"))?
}

pub fn desktop_lnk(product: &str) -> Option<PathBuf> {
    dirs::desktop_dir().map(|d| d.join(format!("{product}.lnk")))
}

pub fn start_menu_dir(product: &str) -> Option<PathBuf> {
    dirs::data_dir().map(|d| d.join("Microsoft\\Windows\\Start Menu\\Programs").join(product))
}

fn uninstall_key(product: &str) -> String {
    format!("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{product}")
}

pub fn register_uninstall(product: &str, publisher: &str, version: &str, dir: &Path, exe: &Path) -> Result<()> {
    use winreg::enums::HKEY_CURRENT_USER;
    let hkcu = winreg::RegKey::predef(HKEY_CURRENT_USER);
    let (k, _) = hkcu.create_subkey(uninstall_key(product))?;
    let exe_s = exe.to_string_lossy().to_string();
    k.set_value("DisplayName", &product.to_string())?;
    k.set_value("DisplayVersion", &version.to_string())?;
    k.set_value("Publisher", &publisher.to_string())?;
    k.set_value("InstallLocation", &dir.to_string_lossy().to_string())?;
    k.set_value("DisplayIcon", &exe_s)?;
    k.set_value("UninstallString", &format!("\"{exe_s}\" --uninstall"))?;
    k.set_value("NoModify", &1u32)?;
    k.set_value("NoRepair", &1u32)?;
    Ok(())
}

pub fn registered_location(product: &str) -> Option<PathBuf> {
    use winreg::enums::HKEY_CURRENT_USER;
    let k = winreg::RegKey::predef(HKEY_CURRENT_USER).open_subkey(uninstall_key(product)).ok()?;
    let s: String = k.get_value("InstallLocation").ok()?;
    Some(PathBuf::from(s))
}

pub fn unregister_uninstall(product: &str) {
    use winreg::enums::HKEY_CURRENT_USER;
    let _ = winreg::RegKey::predef(HKEY_CURRENT_USER).delete_subkey_all(uninstall_key(product));
}

pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Удалить файл (и пустую папку) после выхода процесса.
pub fn delete_after_exit(file: &Path, dir: Option<&Path>) {
    use std::os::windows::process::CommandExt;
    let mut cmd = format!("ping 127.0.0.1 -n 3 >NUL & del /F /Q \"{}\"", file.display());
    if let Some(d) = dir {
        cmd.push_str(&format!(" & rmdir \"{}\"", d.display()));
    }
    let _ = std::process::Command::new("cmd").raw_arg(format!("/C {cmd}")).creation_flags(CREATE_NO_WINDOW).spawn();
}

pub fn open_url(url: &str) -> Result<()> {
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err(anyhow!("недопустимая ссылка"));
    }
    std::process::Command::new("explorer").arg(url).spawn()?;
    Ok(())
}

pub struct LogFile {
    path: PathBuf,
    lock: parking_lot::Mutex<()>,
}

impl LogFile {
    pub fn new(dir: &Path) -> Self {
        Self { path: dir.join(".launcher").join("logs").join("launcher.log"), lock: parking_lot::Mutex::new(()) }
    }

    pub fn line(&self, s: &str) {
        let _g = self.lock.lock();
        if let Some(p) = self.path.parent() {
            let _ = std::fs::create_dir_all(p);
        }
        if std::fs::metadata(&self.path).map(|m| m.len() > 2 << 20).unwrap_or(false) {
            let _ = std::fs::rename(&self.path, self.path.with_extension("log.1"));
        }
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&self.path) {
            let _ = writeln!(f, "{} {s}", local_time());
        }
    }
}

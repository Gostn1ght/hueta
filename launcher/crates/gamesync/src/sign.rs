use crate::manifest::{hex32, Release, SignedRelease};
use anyhow::{anyhow, Result};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};

pub fn public_from_secret(secret_hex: &str) -> Result<String> {
    let sk = SigningKey::from_bytes(&hex32(secret_hex)?);
    Ok(hex::encode(sk.verifying_key().to_bytes()))
}

pub fn sign_release(r: &Release, secret_hex: &str) -> Result<String> {
    let sk = SigningKey::from_bytes(&hex32(secret_hex)?);
    let payload = serde_json::to_string(r)?;
    let sig = sk.sign(payload.as_bytes());
    Ok(serde_json::to_string_pretty(&SignedRelease {
        payload,
        signature: hex::encode(sig.to_bytes()),
    })?)
}

pub fn verify_release(bytes: &[u8], public_hex: &str) -> Result<Release> {
    let s: SignedRelease = serde_json::from_slice(bytes).map_err(|e| anyhow!("latest.json повреждён: {e}"))?;
    let vk = VerifyingKey::from_bytes(&hex32(public_hex)?)?;
    let sig: [u8; 64] = hex::decode(&s.signature)?
        .try_into()
        .map_err(|_| anyhow!("неверная длина подписи"))?;
    vk.verify(s.payload.as_bytes(), &Signature::from_bytes(&sig))
        .map_err(|_| anyhow!("подпись релиза не прошла проверку — сервер подменён или ключ не тот"))?;
    Ok(serde_json::from_str(&s.payload)?)
}

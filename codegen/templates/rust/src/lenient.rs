// Readers for the downloaded report types. A report is written by the AI
// pipeline, so a field can be null, missing, or a decimal where a whole
// number is expected; none of those may fail the decode.

use serde::{Deserialize, Deserializer};

/// Reads null as the type's default.
pub fn null_default<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de> + Default,
{
    Ok(Option::<T>::deserialize(deserializer)?.unwrap_or_default())
}

/// Reads a whole number, a decimal (rounded to the nearest) or null (0).
pub fn int<'de, D: Deserializer<'de>>(deserializer: D) -> Result<i64, D::Error> {
    Ok(opt_int(deserializer)?.unwrap_or_default())
}

/// Reads a whole number, a decimal (rounded to the nearest) or null (`None`).
pub fn opt_int<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Option<i64>, D::Error> {
    let number = Option::<serde_json::Number>::deserialize(deserializer)?;
    Ok(number.and_then(|n| n.as_i64().or_else(|| n.as_f64().map(|f| f.round() as i64))))
}

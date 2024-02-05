
function isMarkableElementOverride(element) {
  // Allow clicking on Re-Captcha frames
  if (element.id === "recaptcha-anchor")
    return true;

  // Allow clicking on the OTP login button
  if (["Log in item_id__1__", "Log in"].includes(element.getAttribute("aria-label")))
    return true;

  // Allow the default behaviour to kick in 
  return null;
}
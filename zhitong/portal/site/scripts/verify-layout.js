return await (async () => {
  document.documentElement.removeAttribute('data-layout-checked');
  const results = [];
  const flush = () =>
    new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  for (const group of document.querySelectorAll('.capability-tabs [role="tab"]')) {
    group.click();
    await flush();
    const panel = document.getElementById(group.getAttribute('aria-controls'));
    for (const summary of panel.querySelectorAll('summary')) {
      if (!summary.parentElement.open) summary.click();
      await flush();
      const detail = summary.parentElement.querySelector('.feature-detail');
      const box = detail.getBoundingClientRect();
      results.push({
        feature: summary.innerText.trim(),
        open: summary.parentElement.open,
        overflow: document.documentElement.scrollWidth > innerWidth,
        detailVisible: box.width > 0 && box.height > 0,
      });
    }
  }
  for (const tab of document.querySelectorAll('.scenario-tabs [role="tab"]')) {
    tab.click();
    await flush();
    results.push({
      scene: tab.innerText.trim(),
      overflow: document.documentElement.scrollWidth > innerWidth,
    });
  }
  window.__layoutResult = {
    width: innerWidth,
    checked: results.length,
    failures: results.filter(
      (result) => result.overflow || result.open === false || result.detailVisible === false,
    ),
  };
  document.documentElement.dataset.layoutChecked = String(innerWidth);
  return window.__layoutResult;
})();

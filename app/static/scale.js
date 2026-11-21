const form = document.getElementById('calculate');
const notice = document.getElementById('notice');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  notice.value = '正在复算…';
  delete notice.dataset.error;
  try {
    const response = await fetch(form.action, {method: 'POST', body: new FormData(form)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail);
    location.assign(result.next);
  } catch (error) {
    notice.dataset.error = '';
    notice.value = error.message || '复算失败，请重试。';
    button.disabled = false;
  }
});

const release = document.getElementById('release');
if (release) {
  const releaseNotice = document.getElementById('release-notice');
  release.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = release.querySelector('button');
    button.disabled = true;
    try {
      const response = await fetch(release.action, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '暂缓发运');
      releaseNotice.value = '已移交发运。';
      releaseNotice.dataset.ok = '';
    } catch (error) {
      releaseNotice.dataset.error = '';
      releaseNotice.value = error.message;
      button.disabled = false;
    }
  });
}

const refresh = document.getElementById('refresh');
if (refresh) {
  refresh.addEventListener('click', async () => {
    const notice = document.getElementById('release-notice');
    refresh.disabled = true;
    try {
      const response = await fetch(`/api/runs/${refresh.dataset.key}/refresh`, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail);
      location.reload();
    } catch (error) {
      delete notice.dataset.ok;
      notice.dataset.error = '';
      notice.value = error.message || '重算失败，已保留旧版处置单。';
      refresh.disabled = false;
    }
  });
}

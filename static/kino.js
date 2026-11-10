document.querySelectorAll("[data-range-output]").forEach((input) => {
  const output = document.getElementById(input.dataset.rangeOutput);
  if (!output) return;
  const update = () => { output.value = input.value; output.textContent = input.value; };
  input.addEventListener("input", update);
  update();
});

document.querySelectorAll("[data-compare-picker]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const selection = form.querySelector("select[name='movie']");
    const warning = form.querySelector("[data-compare-error]");
    const tooMany = selection && selection.selectedOptions.length > 4;
    if (warning) warning.hidden = !tooMany;
    if (tooMany) event.preventDefault();
  });
});

const readChartData = (id) => {
  const node = document.getElementById(id);
  return node ? JSON.parse(node.textContent) : null;
};

if (window.Chart) {
  Chart.defaults.color = "#9ba9a1";
  Chart.defaults.borderColor = "#2b3731";
  Chart.defaults.font.family = "Aptos, Segoe UI, sans-serif";

  const imdb = readChartData("imdb-history-data");
  const imdbCanvas = document.getElementById("imdb-history-chart");
  if (imdb && imdbCanvas) {
    new Chart(imdbCanvas, {
      type: "line",
      data: { labels: imdb.labels, datasets: [{ data: imdb.scores, borderColor: "#e1b779", backgroundColor: "rgba(225,183,121,.12)", pointRadius: 2, borderWidth: 2, fill: true, tension: .2 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 10, grid: { color: "#26312b" } }, x: { grid: { display: false } } } },
    });
  }

  const watched = readChartData("watched-chart-data");
  const watchedCanvas = document.getElementById("watched-chart");
  if (watched && watchedCanvas) {
    new Chart(watchedCanvas, {
      type: "bar",
      data: { labels: watched.labels, datasets: [{ data: watched.values, backgroundColor: "#4e9e71", borderRadius: 1 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#26312b" } }, x: { grid: { display: false } } } },
    });
  }

  const genres = readChartData("genre-chart-data");
  const genreCanvas = document.getElementById("genre-chart");
  if (genres && genreCanvas && genres.labels.length) {
    new Chart(genreCanvas, {
      type: "doughnut",
      data: { labels: genres.labels, datasets: [{ data: genres.values, backgroundColor: ["#77d7a4", "#e1b779", "#7ca9c8", "#c98e75", "#a6a0cf", "#8ab2a0"], borderColor: "#131a17", borderWidth: 2 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: "right", labels: { boxWidth: 10, padding: 10 } } } },
    });
  }
}
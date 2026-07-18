package com.aksemple.soundlocator

import android.content.pm.ActivityInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aksemple.soundlocator.ui.theme.SoundLocatorTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.pow

private const val PAGE_SIZE = 15

// One distinct, light-theme-friendly color per recorded channel (value1..value4).
private val channelColors = listOf(
    Color(0xFFD32F2F), // ch1 red
    Color(0xFF388E3C), // ch2 green
    Color(0xFF1976D2), // ch3 blue
    Color(0xFFF57C00), // ch4 orange
)

class BrowseDatabaseActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        setContent {
            SoundLocatorTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    BrowseDatabaseScreen()
                }
            }
        }
    }
}

@Composable
private fun BrowseDatabaseScreen() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val db = remember { AppDatabase.getInstance(context) }
    val scope = rememberCoroutineScope()

    val captures = remember { mutableStateListOf<CaptureListItem>() }
    var isLoading by remember { mutableStateOf(false) }
    var endReached by remember { mutableStateOf(false) }
    var selectedId by remember { mutableStateOf<Long?>(null) }

    var waveform by remember { mutableStateOf<List<SoundData>>(emptyList()) }
    var waveLoading by remember { mutableStateOf(false) }

    fun loadNextPage() {
        if (isLoading || endReached) return
        isLoading = true
        scope.launch {
            try {
                val page = withContext(Dispatchers.IO) {
                    db.capturesDao().getCapturesPaged(PAGE_SIZE, captures.size)
                }
                captures.addAll(page)
                if (page.size < PAGE_SIZE) endReached = true
            } catch (e: Exception) {
                android.util.Log.e("BrowseDatabase", "Failed to load captures page", e)
                endReached = true   // stop the spinner instead of hanging forever
            } finally {
                isLoading = false
            }
        }
    }

    LaunchedEffect(Unit) { loadNextPage() }

    Row(modifier = Modifier.fillMaxSize()) {
        // Left 2/3 - waveform of the selected capture
        Box(modifier = Modifier.weight(2f).fillMaxHeight()) {
            WaveformView(rows = waveform, loading = waveLoading, hasSelection = selectedId != null)
        }
        VerticalDivider(
            modifier = Modifier.fillMaxHeight(),
            color = MaterialTheme.colorScheme.outlineVariant
        )
        // Right 1/3 - lazily loaded capture list
        Box(modifier = Modifier.weight(1f).fillMaxHeight()) {
            CaptureListPane(
                captures = captures,
                selectedId = selectedId,
                isLoading = isLoading,
                endReached = endReached,
                onLoadMore = { loadNextPage() },
                onSelect = { item ->
                    selectedId = item.id
                    waveLoading = true
                    waveform = emptyList()
                    scope.launch {
                        val rows = withContext(Dispatchers.IO) {
                            db.soundDataDao().loadByCaptureIdOrdered(item.id)
                        }
                        waveform = rows
                        waveLoading = false
                    }
                }
            )
        }
    }
}

@Composable
private fun CaptureListPane(
    captures: List<CaptureListItem>,
    selectedId: Long?,
    isLoading: Boolean,
    endReached: Boolean,
    onLoadMore: () -> Unit,
    onSelect: (CaptureListItem) -> Unit,
) {
    val listState = rememberLazyListState()

    // Trigger loading the next page as the user approaches the bottom.
    LaunchedEffect(listState, captures.size, endReached) {
        snapshotFlow {
            listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
        }.distinctUntilChanged().collect { lastVisible ->
            if (!endReached && lastVisible >= captures.size - 3) onLoadMore()
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            text = "Captures",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(12.dp)
        )
        HorizontalDivider()
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
            items(items = captures, key = { it.id }) { item ->
                CaptureRow(
                    item = item,
                    selected = item.id == selectedId,
                    onClick = { onSelect(item) }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            }
            if (isLoading || !endReached) {
                item {
                    Box(
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp))
                    }
                }
            }
            if (endReached && captures.isEmpty()) {
                item {
                    Box(
                        modifier = Modifier.fillMaxWidth().padding(24.dp),
                        contentAlignment = Alignment.Center
                    ) { Text("No captures in database") }
                }
            }
        }
    }
}

private val dateFormat = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault())

@Composable
private fun CaptureRow(item: CaptureListItem, selected: Boolean, onClick: () -> Unit) {
    val bg = if (selected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp)
    ) {
        Text(
            text = dateFormat.format(Date(item.timestamp)),
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium
        )
        Spacer(Modifier.height(2.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = "#${item.id}  ·  ${item.soundCount} samples",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (item.isOverrun != 0) {
                Text(
                    text = "overrun: ${item.isOverrun}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@Composable
private fun WaveformView(rows: List<SoundData>, loading: Boolean, hasSelection: Boolean) {
    if (rows.isEmpty()) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                when {
                    loading -> "Loading waveform…"
                    !hasSelection -> "Select a capture to view its waveform"
                    else -> "This capture has no sound data"
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        return
    }

    val n = rows.size
    // Column-major channel arrays for fast drawing, recomputed only when data changes.
    val channels = remember(rows) {
        Array(4) { ch ->
            IntArray(n) { i ->
                when (ch) {
                    0 -> rows[i].value1
                    1 -> rows[i].value2
                    2 -> rows[i].value3
                    else -> rows[i].value4
                }
            }
        }
    }
    val yMinMax = remember(rows) {
        var mn = Int.MAX_VALUE
        var mx = Int.MIN_VALUE
        for (ch in channels) for (v in ch) {
            if (v < mn) mn = v
            if (v > mx) mx = v
        }
        if (mn == mx) { mn -= 1; mx += 1 }
        mn.toFloat() to mx.toFloat()
    }
    val yMin = yMinMax.first
    val yMax = yMinMax.second

    // Image-style view transform (uniform scale + free pan). Reset on new data.
    var scale by remember(rows) { mutableFloatStateOf(1f) }
    var offset by remember(rows) { mutableStateOf(Offset.Zero) }

    val textMeasurer = rememberTextMeasurer()
    val axisColor = MaterialTheme.colorScheme.outline
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val labelStyle = TextStyle(color = labelColor, fontSize = 10.sp)

    Box(modifier = Modifier.fillMaxSize()) {
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(rows) {
                    detectTransformGestures { centroid, pan, zoom, _ ->
                        val newScale = (scale * zoom).coerceIn(0.25f, 500f)
                        // Keep the point under the gesture centroid stationary, then pan.
                        offset = centroid + pan - (centroid - offset) * (newScale / scale)
                        scale = newScale
                    }
                }
        ) {
            val marginLeft = 68f
            val marginBottom = 44f
            val marginTop = 16f
            val marginRight = 16f
            val plotW = (size.width - marginLeft - marginRight).coerceAtLeast(1f)
            val plotH = (size.height - marginTop - marginBottom).coerceAtLeast(1f)
            val ox = marginLeft
            val oy = marginTop

            // data -> plot-local base coords (full data fit into plot rect)
            fun baseX(i: Float) = if (n > 1) i / (n - 1) * plotW else plotW / 2f
            fun baseY(v: Float) = plotH - (v - yMin) / (yMax - yMin) * plotH
            // plot-local -> screen (apply user scale + pan)
            fun sx(i: Float) = ox + baseX(i) * scale + offset.x
            fun sy(v: Float) = oy + baseY(v) * scale + offset.y
            // inverse helpers (screen plot-local -> data)
            fun screenXToIndex(px: Float): Float {
                val baseX = (px - ox - offset.x) / scale
                return if (n > 1) baseX / plotW * (n - 1) else 0f
            }
            fun screenYToAmp(py: Float): Float {
                val baseY = (py - oy - offset.y) / scale
                return yMin + (plotH - baseY) / plotH * (yMax - yMin)
            }

            // ---- gridlines + axis labels (computed from the visible range) ----
            val iLeft = screenXToIndex(ox).coerceIn(0f, (n - 1).toFloat())
            val iRight = screenXToIndex(ox + plotW).coerceIn(0f, (n - 1).toFloat())
            val ampTop = screenYToAmp(oy)        // amplitude at top edge of plot
            val ampBottom = screenYToAmp(oy + plotH)

            val xStep = niceStep(iRight - iLeft, 6)
            var xt = ceil(iLeft / xStep) * xStep
            while (xt <= iRight) {
                val px = sx(xt)
                drawLine(gridColor, Offset(px, oy), Offset(px, oy + plotH), 1f)
                val label = xt.toLong().toString()
                val m = textMeasurer.measure(label, labelStyle)
                drawText(m, topLeft = Offset(px - m.size.width / 2f, oy + plotH + 6f))
                xt += xStep
            }

            val yStep = niceStep(ampTop - ampBottom, 6)
            var yt = ceil(ampBottom / yStep) * yStep
            while (yt <= ampTop) {
                val py = sy(yt)
                drawLine(gridColor, Offset(ox, py), Offset(ox + plotW, py), 1f)
                val label = yt.toLong().toString()
                val m = textMeasurer.measure(label, labelStyle)
                drawText(m, topLeft = Offset(ox - m.size.width - 6f, py - m.size.height / 2f))
                yt += yStep
            }

            // ---- waveforms, clipped to the plot rect ----
            clipRect(ox, oy, ox + plotW, oy + plotH) {
                // Bound work: never build more than ~2 points per horizontal pixel.
                val li = floor(iLeft).toInt().coerceIn(0, n - 1)
                val ri = ceil(iRight).toInt().coerceIn(0, n - 1)
                val visN = (ri - li).coerceAtLeast(1)
                val step = max(1, visN / (plotW.toInt().coerceAtLeast(1) * 2))
                for (ch in 0 until 4) {
                    val data = channels[ch]
                    val path = Path()
                    var first = true
                    var i = li
                    while (i <= ri) {
                        val px = sx(i.toFloat())
                        val py = sy(data[i].toFloat())
                        if (first) { path.moveTo(px, py); first = false } else path.lineTo(px, py)
                        i += step
                    }
                    // ensure the final sample is drawn
                    if ((ri - li) % step != 0) {
                        path.lineTo(sx(ri.toFloat()), sy(data[ri].toFloat()))
                    }
                    drawPath(path, color = channelColors[ch], style = Stroke(width = 2f))
                }
            }

            // ---- axis frame ----
            drawLine(axisColor, Offset(ox, oy), Offset(ox, oy + plotH), 2f)
            drawLine(axisColor, Offset(ox, oy + plotH), Offset(ox + plotW, oy + plotH), 2f)

            // ---- axis titles ----
            val xTitle = textMeasurer.measure("sample index", labelStyle)
            drawText(xTitle, topLeft = Offset(ox + plotW / 2f - xTitle.size.width / 2f, size.height - xTitle.size.height))
            val yTitle = textMeasurer.measure("amplitude", labelStyle)
            drawText(yTitle, topLeft = Offset(2f, oy - yTitle.size.height - 2f))
        }

        // Channel legend
        Row(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(8.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            for (ch in 0 until 4) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(10.dp)
                            .background(channelColors[ch])
                    )
                    Spacer(Modifier.width(3.dp))
                    Text("ch${ch + 1}", style = MaterialTheme.typography.labelSmall)
                }
            }
        }

        // Reset-view control
        TextButton(
            onClick = { scale = 1f; offset = Offset.Zero },
            modifier = Modifier.align(Alignment.BottomEnd).padding(4.dp)
        ) { Text("Fit") }
    }
}

/** Round a raw axis range/target-count into a human-friendly 1/2/5·10^k step. */
private fun niceStep(range: Float, targetTicks: Int): Float {
    if (range <= 0f || targetTicks <= 0) return 1f
    val raw = range / targetTicks
    val mag = 10f.pow(floor(log10(raw.toDouble())).toFloat())
    val norm = raw / mag
    val niceNorm = when {
        norm < 1.5f -> 1f
        norm < 3f -> 2f
        norm < 7f -> 5f
        else -> 10f
    }
    return (niceNorm * mag).coerceAtLeast(1f)
}
